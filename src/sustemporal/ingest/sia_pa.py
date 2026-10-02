"""Normalização do SIA-PA preservando multiplicidade (T03).

Uma linha canônica por registro físico do DBF, inclusive deletados, sem deduplicação nem filtro.
Cada campo normalizado guarda o valor, o texto bruto (latin-1, sem aparar) e o motivo de ausência.
"""

from __future__ import annotations

import codecs
import hashlib
import logging
import tempfile
from contextlib import closing
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    DatasetRef,
    EsquemaCanonico,
    EstadoIntegridade,
    FamiliaFonte,
    FormatoArquivo,
    FormatoLeiaute,
    MotivoAusencia,
    Multiplicidade,
    OrigemDados,
    Reconciliacao,
    RuntimeConfig,
    TipoCanonico,
    calcular_dataset_id,
)
from sustemporal.duck import conectar, identificador_seguro
from sustemporal.hashing import hash_logico_relacao, sha256_arquivo
from sustemporal.ingest.dbc import ler_dbc_arquivo, verificar_fidelidade
from sustemporal.ingest.dbf import (
    COLUNA_DELETADO,
    COLUNA_INDICE,
    ArquivoAusente,
    QuarentenaLeitura,
    compactar,
    ler_dbf_arquivo,
)
from sustemporal.store import caminho_conteudo

if TYPE_CHECKING:
    import duckdb

    from sustemporal.contracts import ArtifactVersion, CampoLeiaute, LayoutSpec
    from sustemporal.ingest.dbf import CabecalhoDbf, DescritorCampo, LeituraDbf

logger = logging.getLogger(__name__)

RAIZ_CATALOGO = Path(__file__).resolve().parents[3] / "catalog"
ESQUEMA_PA = RAIZ_CATALOGO / "schemas" / "sia_pa.yaml"
TABELA = "sia_pa"

PADROES: dict[str, str] = {
    "cnes": r"^[0-9]{7}$",
    "municipio_estabelecimento": r"^[0-9]{6}$",
    "tipo_unidade": r"^[0-9]{2}$",
    "competencia_processamento": r"^[0-9]{4}(0[1-9]|1[0-2])$",
    "competencia_atendimento": r"^[0-9]{4}(0[1-9]|1[0-2])$",
    "procedimento": r"^[0-9]{10}$",
    "instrumento": r"^[CIPSAB]$",
    "cbo": r"^[0-9A-Z]{6}$",
    "cid_principal": r"^[A-Z][0-9]{2}[0-9A-Z]?$",
    "cid_secundario": r"^[A-Z][0-9]{2}[0-9A-Z]?$",
    "cid_causas_associadas": r"^[A-Z][0-9]{2}[0-9A-Z]?$",
    "carater_atendimento": r"^[0-9]{2}$",
    "sexo": r"^[MF]$",
}
CAMPOS_DESCARTADOS = frozenset(
    {"pa_cnpjcpf", "pa_cnpjmnt", "pa_cnpj_cc", "pa_autoriz", "pa_cnsmed", "pa_fntorc"}
)
_INTEIRO = r"^[0-9]+$"
_SEM_LINHAGEM = frozenset({"row_id", "indice_registro"})


def _leiaute(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_LEIAUTE, motivo)


def _conferir_descritor(lido: DescritorCampo, esperado: CampoLeiaute) -> None:
    fisico = (lido.tipo, lido.largura, lido.decimais)
    alvo = (esperado.tipo_fisico, esperado.largura, esperado.decimais)
    if fisico != alvo or esperado.inicio not in {None, lido.inicio}:
        raise _leiaute(
            f"descritor_divergente campo={lido.nome} lido={compactar(fisico)} "
            f"esperado={compactar(alvo)}"
        )


def _latin1(codificacao: str) -> bool:
    try:
        return codecs.lookup(codificacao).name == "iso8859-1"
    except LookupError:
        return False


def _conferir_vigencia(artifact: ArtifactVersion, layout: LayoutSpec) -> None:
    competencia = artifact.chave.competencia_arquivo
    if layout.valido_de is None and layout.valido_ate is None:
        return
    fora = competencia is None or not (
        (layout.valido_de is None or layout.valido_de <= competencia)
        and (layout.valido_ate is None or competencia <= layout.valido_ate)
    )
    if fora:
        raise _leiaute(
            f"leiaute_fora_da_vigencia layout={layout.layout_id} competencia={competencia}"
        )


def casar_leiaute(cabecalho: CabecalhoDbf, layout: LayoutSpec) -> tuple[CampoLeiaute, ...]:
    """Campos do leiaute presentes no arquivo, na ordem física; o resto vai para quarentena.

    Campos com `obrigatorio` falso podem faltar; os presentes seguem a ordem do leiaute.
    """
    if layout.formato is not FormatoLeiaute.DBF:
        raise _leiaute(f"leiaute_nao_dbf layout={layout.layout_id} formato={layout.formato}")
    if not _latin1(layout.codificacao):
        raise _leiaute(f"codificacao_nao_latin1 layout={layout.layout_id}")
    restantes = list(layout.campos)
    casados: list[CampoLeiaute] = []
    for posicao, lido in enumerate(cabecalho.campos):
        while restantes and restantes[0].nome_fisico != lido.nome and not restantes[0].obrigatorio:
            restantes.pop(0)
        if not restantes or restantes[0].nome_fisico != lido.nome:
            raise _leiaute(f"campo_inesperado campo={compactar(lido.nome)} posicao={posicao}")
        esperado = restantes.pop(0)
        _conferir_descritor(lido, esperado)
        casados.append(esperado)
    faltantes = [campo.nome_fisico for campo in restantes if campo.obrigatorio]
    if faltantes:
        raise _leiaute(f"campos_obrigatorios_ausentes campos={compactar(faltantes)}")
    return tuple(casados)


_EXTENSOES = {FormatoArquivo.DBC: "dbc", FormatoArquivo.DBF: "dbf"}


def _caminho_seguro(artifact: ArtifactVersion, raiz_dados: Path) -> Path:
    """Caminho do conteúdo derivado do sha256 e confinado à raiz de dados (sem link para fora)."""
    extensao = _EXTENSOES.get(artifact.formato)
    if extensao is None:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, f"formato={artifact.formato}"
        )
    raiz = raiz_dados.resolve()
    esperado = caminho_conteudo(raiz, artifact.sha256, extensao)
    informado = Path(artifact.caminho_conteudo)
    resolvido = (informado if informado.is_absolute() else raiz / informado).resolve()
    if resolvido != esperado or not resolvido.is_relative_to(raiz):
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO,
            f"caminho_fora_do_enderecamento id={artifact.artifact_id}",
        )
    return esperado


def _exigir_integro(artifact: ArtifactVersion, layout: LayoutSpec, runtime: RuntimeConfig) -> Path:
    if artifact.integridade is not EstadoIntegridade.OK:
        raise QuarentenaLeitura(
            artifact.integridade, f"artefato_nao_integro id={artifact.artifact_id}"
        )
    _conferir_vigencia(artifact, layout)
    if layout.fonte is not FamiliaFonte.SIA_PA or artifact.chave.fonte is not FamiliaFonte.SIA_PA:
        raise _leiaute(f"fonte_incompativel layout={layout.layout_id} id={artifact.artifact_id}")
    caminho = _caminho_seguro(artifact, Path(runtime.raiz_dados))
    if not caminho.is_file():
        raise ArquivoAusente(f"arquivo_ausente id={artifact.artifact_id}")
    if sha256_arquivo(caminho) != artifact.sha256:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CHECKSUM, f"sha256_divergente id={artifact.artifact_id}"
        )
    return caminho


def _ler(artifact: ArtifactVersion, caminho: Path, runtime: RuntimeConfig) -> LeituraDbf:
    """Lê os bytes uma vez; a mesma cópia vai à descompressão limitada e à fidelidade."""
    dados = caminho.read_bytes()
    if hashlib.sha256(dados).hexdigest() != artifact.sha256:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CHECKSUM, f"sha256_divergente id={artifact.artifact_id}"
        )
    with tempfile.TemporaryDirectory() as nome_pasta:
        copia = Path(nome_pasta) / f"artefato.{_EXTENSOES[artifact.formato]}"
        copia.write_bytes(dados)
        if artifact.formato is FormatoArquivo.DBF:
            return ler_dbf_arquivo(copia)
        leitura = ler_dbc_arquivo(copia, dir_temporario=Path(nome_pasta)).leitura
    modo = runtime.verificacao_fidelidade
    if modo == "DESLIGADA":
        return leitura
    relatorio = verificar_fidelidade(dados, leitura, modo)
    if not relatorio.fiel:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO,
            f"fidelidade_reprovada divergencias={compactar(list(relatorio.divergencias))}",
        )
    return leitura


class _Consulta:
    """Monta o SELECT canônico com identificadores de allowlist e literais parametrizados."""

    def __init__(self, fisicos: set[str], saida: set[str]) -> None:
        self._fisicos = fisicos
        self._saida = saida
        self.expressoes: list[str] = []
        self.parametros: dict[str, object] = {}

    def parametro(self, valor: object) -> str:
        nome = f"p{len(self.parametros)}"
        self.parametros[nome] = valor
        return f"${nome}"

    def bruto(self, nome_fisico: str) -> str:
        return identificador_seguro(nome_fisico.lower(), self._fisicos)

    def coluna(self, expressao: str, nome: str) -> None:
        self.expressoes.append(f"{expressao} AS {identificador_seguro(nome, self._saida)}")


def _tipo_sql(tipo: TipoCanonico, decimais: int) -> str:
    return {
        TipoCanonico.TEXTO: "VARCHAR",
        TipoCanonico.INTEIRO: "BIGINT",
        TipoCanonico.DECIMAL: f"DECIMAL(38, {decimais})",
        TipoCanonico.BOOLEANO: "BOOLEAN",
    }[tipo]


def _padrao(campo: CampoLeiaute) -> str | None:
    if campo.tipo_canonico is TipoCanonico.INTEIRO:
        return _INTEIRO if campo.nome_canonico != "idade" or campo.unidade else None
    if campo.tipo_canonico is TipoCanonico.DECIMAL:
        fracao = rf"(\.[0-9]{{1,{campo.decimais}}})?" if campo.decimais else ""
        return rf"^-?[0-9]+{fracao}$"
    return PADROES[campo.nome_canonico]


def _motivo_sql(consulta: _Consulta, campo: CampoLeiaute, aparado: str) -> str:
    casos = [f"WHEN {aparado} = '' THEN {consulta.parametro(MotivoAusencia.VAZIO.value)}"]
    for bruto, motivo in campo.sentinelas.items():
        casos.append(
            f"WHEN {aparado} = {consulta.parametro(bruto)} THEN {consulta.parametro(motivo.value)}"
        )
    padrao = _padrao(campo)
    if padrao is None:
        casos.append(f"WHEN TRUE THEN {consulta.parametro(MotivoAusencia.DESCONHECIDO.value)}")
    else:
        invalido = consulta.parametro(MotivoAusencia.CODIFICACAO_INVALIDA.value)
        casos.append(
            f"WHEN NOT regexp_full_match({aparado}, {consulta.parametro(padrao)}) THEN {invalido}"
        )
    return f"CASE {' '.join(casos)} END"


def _normalizado(consulta: _Consulta, campo: CampoLeiaute) -> None:
    nome, bruto = campo.nome_canonico, consulta.bruto(campo.nome_fisico)
    aparado = f"trim({bruto}, ' ')"
    motivo = _motivo_sql(consulta, campo, aparado)
    tipo = _tipo_sql(campo.tipo_canonico, campo.decimais)
    valor = aparado if campo.tipo_canonico is TipoCanonico.TEXTO else f"CAST({aparado} AS {tipo})"
    consulta.coluna(f"CASE WHEN ({motivo}) IS NULL THEN {valor} END", nome)
    consulta.coluna(bruto, f"{nome}_bruto")
    consulta.coluna(motivo, f"{nome}_motivo")


def _ausente(consulta: _Consulta, campo: CampoLeiaute, normalizado: bool) -> None:
    nome = campo.nome_canonico
    consulta.coluna(f"CAST(NULL AS {_tipo_sql(campo.tipo_canonico, campo.decimais)})", nome)
    if normalizado:
        consulta.coluna("CAST(NULL AS VARCHAR)", f"{nome}_bruto")
        consulta.coluna(consulta.parametro(MotivoAusencia.DESCONHECIDO.value), f"{nome}_motivo")


def _campo(consulta: _Consulta, campo: CampoLeiaute, presente: bool, esquema: set[str]) -> None:
    normalizado = f"{campo.nome_canonico}_bruto" in esquema
    if not normalizado and campo.tipo_canonico is not TipoCanonico.TEXTO:
        raise ValueError(f"campo_bruto_deve_ser_texto campo={campo.nome_fisico}")
    if not presente:
        _ausente(consulta, campo, normalizado)
    elif normalizado:
        _normalizado(consulta, campo)
    else:
        consulta.coluna(consulta.bruto(campo.nome_fisico), campo.nome_canonico)
    if campo.nome_canonico == "idade":
        unidade = campo.unidade if presente else None
        consulta.coluna(f"CAST({consulta.parametro(unidade)} AS VARCHAR)", "idade_unidade")


def _consulta_canonica(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    casados: tuple[CampoLeiaute, ...],
    esquema: EsquemaCanonico,
) -> _Consulta:
    fisicos = {COLUNA_INDICE, COLUNA_DELETADO, *(c.nome_fisico.lower() for c in casados)}
    nomes = [coluna.nome for coluna in esquema.colunas]
    consulta = _Consulta(fisicos, set(nomes))
    artefato = consulta.parametro(artifact.artifact_id)
    indice = identificador_seguro(COLUNA_INDICE, fisicos)
    consulta.coluna(f"{artefato} || '#' || CAST({indice} AS VARCHAR)", "row_id")
    consulta.coluna(artefato, "artifact_id")
    consulta.coluna("CAST(NULL AS VARCHAR)", "membro")
    consulta.coluna(indice, "indice_registro")
    consulta.coluna(identificador_seguro(COLUNA_DELETADO, fisicos), "deletado")
    presentes = {campo.nome_fisico for campo in casados}
    for campo in layout.campos:
        if campo.nome_canonico not in CAMPOS_DESCARTADOS:
            _campo(consulta, campo, campo.nome_fisico in presentes, set(nomes))
    return consulta


def _criar_canonica(con: duckdb.DuckDBPyConnection, consulta: _Consulta, ordem: list[str]) -> None:
    por_nome = {
        expressao.rsplit(" AS ", 1)[1].strip('"'): expressao for expressao in consulta.expressoes
    }
    if sorted(por_nome) != sorted(ordem):
        faltando = sorted(set(ordem) ^ set(por_nome))
        raise ValueError(f"esquema_sem_correspondencia colunas={compactar(faltando)}")
    selecao = ", ".join(por_nome[nome] for nome in ordem)
    indice = identificador_seguro(COLUNA_INDICE, {COLUNA_INDICE})
    sql = f"CREATE TABLE {TABELA} AS SELECT {selecao} FROM bruto ORDER BY {indice}"  # noqa: S608
    con.execute(sql, consulta.parametros)


def _multiplicidade(con: duckdb.DuckDBPyConnection, colunas: list[str]) -> Multiplicidade:
    conteudo = [identificador_seguro(c, set(colunas)) for c in colunas if c not in _SEM_LINHAGEM]
    grupos = ", ".join(conteudo)
    linha = con.execute(
        f"SELECT coalesce(sum(n), 0), count(*), coalesce(max(n), 0) "  # noqa: S608
        f"FROM (SELECT count(*) AS n FROM {TABELA} GROUP BY {grupos})"
    ).fetchone()
    if linha is None:
        raise ValueError(f"multiplicidade_sem_resultado tabela={TABELA}")
    return Multiplicidade(
        linhas_totais=int(linha[0]),
        combinacoes_distintas=int(linha[1]),
        max_repeticoes=int(linha[2]),
    )


def gravar_parquet(con: duckdb.DuckDBPyConnection, tabela: str, destino: Path) -> None:
    temporario = destino.with_name(f".{destino.name}.tmp")
    con.table(tabela).write_parquet(str(temporario))
    temporario.replace(destino)


def _materializar(
    con: duckdb.DuckDBPyConnection,
    leitura: LeituraDbf,
    consulta: _Consulta,
    canonico: EsquemaCanonico,
    *,
    artifact_id: str,
    out: Path,
) -> tuple[str, Multiplicidade, str, Path]:
    colunas = [coluna.nome for coluna in canonico.colunas]
    bruto = leitura.tabela.rename_columns([nome.lower() for nome in leitura.tabela.column_names])
    con.register("bruto", bruto)
    _criar_canonica(con, consulta, colunas)
    hash_logico = hash_logico_relacao(con, TABELA, colunas)
    multiplicidade = _multiplicidade(con, colunas)
    dataset_id = calcular_dataset_id(canonico.schema_id, hash_logico, (artifact_id,))
    destino = out / f"{dataset_id}.parquet"
    gravar_parquet(con, TABELA, destino)
    return hash_logico, multiplicidade, dataset_id, destino


def produtor(funcao: str) -> str:
    return f"sustemporal.{funcao}@{metadata.version('sus-temporal')}"


def normalize_pa(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.REAL,
    esquema: Path | None = None,
) -> DatasetRef:
    """Normaliza um artefato SIA-PA para o esquema canônico sia_pa.v1.

    Raises:
        QuarentenaLeitura: artefato não íntegro, arquivo truncado, leiaute incompatível ou
            leitura reprovada na verificação de fidelidade.
        ArquivoAusente: conteúdo do artefato inexistente.
    """
    configuracao = runtime or RuntimeConfig()
    canonico = EsquemaCanonico.de_yaml(esquema or ESQUEMA_PA)
    caminho = _exigir_integro(artifact, layout, configuracao)
    leitura = _ler(artifact, caminho, configuracao)
    casados = casar_leiaute(leitura.cabecalho, layout)
    consulta = _consulta_canonica(artifact, layout, casados, canonico)
    with closing(conectar(configuracao)) as con:
        hash_logico, multiplicidade, dataset_id, destino = _materializar(
            con, leitura, consulta, canonico, artifact_id=artifact.artifact_id, out=out
        )
    linhas = multiplicidade.linhas_totais
    descartados = sorted(c.nome_fisico for c in casados if c.nome_canonico in CAMPOS_DESCARTADOS)
    logger.info(
        "sia_pa_normalizado id=%s linhas=%s deletados=%s descartados=%s",
        artifact.artifact_id,
        linhas,
        leitura.n_deletados,
        compactar(descartados),
    )
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=canonico.schema_id,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=(artifact.artifact_id,),
        origem_dados=origem_dados,
        produzido_por=produtor(f"ingest.sia_pa.normalize_pa/{layout.layout_id}"),
        reconciliacao=Reconciliacao(
            fisicos=leitura.tabela.num_rows, deletados=leitura.n_deletados, canonicas=linhas
        ),
        multiplicidade=multiplicidade,
    )


def _tipo_compativel(fisico: str, tipo: TipoCanonico) -> bool:
    if tipo is TipoCanonico.DECIMAL:
        return fisico.startswith("DECIMAL(")
    return (
        fisico
        == {
            TipoCanonico.TEXTO: "VARCHAR",
            TipoCanonico.INTEIRO: "BIGINT",
            TipoCanonico.BOOLEANO: "BOOLEAN",
            TipoCanonico.DATA: "DATE",
        }[tipo]
    )


def carregar_conferido(
    con: duckdb.DuckDBPyConnection, dataset: DatasetRef, esquema: EsquemaCanonico, tabela: str
) -> list[str]:
    """Carrega o Parquet do dataset e confere colunas, tipos físicos, contagem e hash lógico."""
    if dataset.schema_id != esquema.schema_id:
        raise ValueError(f"dataset_divergente esquema={dataset.schema_id}")
    destino = identificador_seguro(tabela, {tabela})
    con.execute(
        f"CREATE TABLE {destino} AS SELECT * FROM read_parquet($caminho)",  # noqa: S608
        {"caminho": dataset.caminho},
    )
    colunas = [coluna.nome for coluna in esquema.colunas]
    descricao = con.execute(f"DESCRIBE {destino}").fetchall()
    lidas = [str(linha[0]) for linha in descricao]
    tipos_ok = all(
        _tipo_compativel(str(linha[1]), coluna.tipo)
        for linha, coluna in zip(descricao, esquema.colunas, strict=False)
    )
    contagem = con.execute(f"SELECT count(*) FROM {destino}").fetchone()  # noqa: S608
    if lidas != colunas or not tipos_ok or contagem is None or contagem[0] != dataset.linhas:
        raise ValueError(f"dataset_divergente dataset_id={dataset.dataset_id} motivo=estrutura")
    if hash_logico_relacao(con, tabela, colunas) != dataset.hash_logico:
        raise ValueError(f"dataset_divergente dataset_id={dataset.dataset_id} motivo=hash")
    return colunas
