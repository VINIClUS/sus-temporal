"""Normalização das tabelas do SIGTAP (T04).

Uma chamada por tabela: o `layout` do catálogo identifica a tabela e o `*_layout.txt` do próprio
zip dá as posições daquela competência. Códigos ficam texto no domínio do motor; idade guarda
bruto e motivo; valores viram DECIMAL com as casas implícitas do catálogo. Uma tabela que não pode
ser lida inteira vai para quarentena: nunca há leitura parcial nem conjunto vazio.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from contextlib import closing
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

import pyarrow as pa

from sustemporal.contracts import (
    DatasetRef,
    EsquemaCanonico,
    EstadoIntegridade,
    FamiliaFonte,
    FormatoArquivo,
    MotivoAusencia,
    Multiplicidade,
    OrigemDados,
    PapelColuna,
    Reconciliacao,
    RuntimeConfig,
    TipoCanonico,
    calcular_dataset_id,
)
from sustemporal.duck import conectar
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura
from sustemporal.ingest.sigtap_zip import (
    LIMITE_MEMBRO_PADRAO,
    conferir_leiaute,
    fatiar,
    ler_leiaute_zip,
    ler_membro,
    tabela_do_leiaute,
)
from sustemporal.store import caminho_conteudo

if TYPE_CHECKING:
    from sustemporal.contracts import ArtifactVersion, CampoLeiaute, LayoutSpec

__all__ = ["ESQUEMAS", "PADROES_CHAVE", "TABELAS", "conferir_anulaveis", "normalize_sigtap"]

logger = logging.getLogger(__name__)

ESQUEMAS = Path(__file__).resolve().parents[3] / "catalog" / "schemas"
TABELAS: dict[str, str] = {
    "tb_procedimento": "sigtap_procedimento",
    "rl_procedimento_ocupacao": "sigtap_proc_ocupacao",
    "rl_procedimento_registro": "sigtap_proc_registro",
    "tb_registro": "sigtap_registro",
}
PADROES_CHAVE: dict[str, re.Pattern[str]] = {
    "co_procedimento": re.compile(r"[0-9]{10}"),
    "co_ocupacao": re.compile(r"[0-9A-Z]{6}"),
    "co_registro": re.compile(r"[0-9]{2}"),
    "dt_competencia": re.compile(r"[0-9]{4}(0[1-9]|1[0-2])"),
}
_DIGITOS = re.compile(r"[0-9]+")
_TABELA_SQL = "sigtap"

Valores = list[object]


def _inesperado(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO, motivo)


def _caminho_seguro(artifact: ArtifactVersion, raiz_dados: Path) -> Path:
    raiz = raiz_dados.resolve()
    esperado = caminho_conteudo(raiz, artifact.sha256, "zip")
    resolvido = Path(artifact.caminho_conteudo).resolve()
    if resolvido != esperado or not resolvido.is_relative_to(raiz):
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO,
            f"caminho_fora_do_enderecamento id={artifact.artifact_id}",
        )
    return esperado


def _bytes_do_artefato(artifact: ArtifactVersion, runtime: RuntimeConfig) -> bytes:
    if artifact.integridade is not EstadoIntegridade.OK:
        raise QuarentenaLeitura(
            artifact.integridade, f"artefato_nao_integro id={artifact.artifact_id}"
        )
    if (
        artifact.chave.fonte is not FamiliaFonte.SIGTAP
        or artifact.formato is not FormatoArquivo.ZIP
    ):
        raise _inesperado(f"artefato_nao_sigtap id={artifact.artifact_id}")
    caminho = _caminho_seguro(artifact, Path(runtime.raiz_dados))
    if not caminho.is_file():
        raise ArquivoAusente(f"arquivo_ausente id={artifact.artifact_id}")
    dados = caminho.read_bytes()
    if hashlib.sha256(dados).hexdigest() != artifact.sha256:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CHECKSUM, f"sha256_divergente id={artifact.artifact_id}"
        )
    return dados


def _membro_declarado(artifact: ArtifactVersion, nome: str) -> None:
    declarados = {m.nome: m.seguro for m in artifact.membros}
    if nome in declarados and not declarados[nome]:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CAMINHO_INSEGURO, f"membro_inseguro nome={nome}"
        )


def _ler_tabela(
    artifact: ArtifactVersion, dados: bytes, tabela: str, limite: int
) -> tuple[bytes, bytes]:
    nomes = (f"{tabela}_layout.txt", f"{tabela}.txt")
    for nome in nomes:
        _membro_declarado(artifact, nome)
    try:
        with zipfile.ZipFile(io.BytesIO(dados)) as arquivo:
            try:
                leiaute = ler_membro(arquivo, nomes[0], limite)
            except ArquivoAusente as erro:
                raise QuarentenaLeitura(
                    EstadoIntegridade.QUARENTENA_LEIAUTE, f"leiaute_ausente tabela={tabela}"
                ) from erro
            return leiaute, ler_membro(arquivo, nomes[1], limite)
    except zipfile.BadZipFile as erro:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_TRUNCADO, f"zip_ilegivel id={artifact.artifact_id}"
        ) from erro


def _chave(brutos: list[str], campo: CampoLeiaute) -> Valores:
    padrao = PADROES_CHAVE[campo.nome_canonico]
    valores: Valores = []
    for indice, bruto in enumerate(brutos):
        valor = bruto.rstrip(" ")
        if padrao.fullmatch(valor) is None:
            raise _inesperado(f"codigo_invalido coluna={campo.nome_canonico} linha={indice}")
        valores.append(valor)
    return valores


def _numero(texto: str, campo: CampoLeiaute, indice: int) -> int | Decimal | None:
    if not texto:
        return None
    if _DIGITOS.fullmatch(texto) is None:
        raise _inesperado(f"numero_invalido coluna={campo.nome_canonico} linha={indice}")
    if campo.tipo_canonico is TipoCanonico.DECIMAL:
        return Decimal(texto).scaleb(-campo.decimais)
    return int(texto)


def _motivo(texto: str, campo: CampoLeiaute) -> str | None:
    if not texto:
        return MotivoAusencia.VAZIO.value
    if texto in campo.sentinelas:
        return campo.sentinelas[texto].value
    if _DIGITOS.fullmatch(texto) is None:
        return MotivoAusencia.CODIFICACAO_INVALIDA.value
    return None


def _com_motivo(brutos: list[str], campo: CampoLeiaute) -> dict[str, Valores]:
    motivos = [_motivo(bruto.strip(" "), campo) for bruto in brutos]
    valores: Valores = [
        None if motivo is not None else int(bruto.strip(" "))
        for bruto, motivo in zip(brutos, motivos, strict=True)
    ]
    nome = campo.nome_canonico
    return {nome: valores, f"{nome}_bruto": list(brutos), f"{nome}_motivo": list(motivos)}


def _colunas_do_campo(
    brutos: list[str], campo: CampoLeiaute, esquema: EsquemaCanonico
) -> dict[str, Valores]:
    nome = campo.nome_canonico
    if esquema.papel_de(f"{nome}_motivo") is PapelColuna.MOTIVO:
        return _com_motivo(brutos, campo)
    if campo.papel is PapelColuna.CHAVE:
        return {nome: _chave(brutos, campo)}
    if campo.tipo_canonico is TipoCanonico.TEXTO:
        return {nome: [bruto.rstrip(" ") or None for bruto in brutos]}
    return {nome: [_numero(b.strip(" "), campo, i) for i, b in enumerate(brutos)]}


def _tipo_arrow(tipo: TipoCanonico, decimais: int) -> pa.DataType:
    if tipo is TipoCanonico.DECIMAL:
        return pa.decimal128(38, decimais)
    return {TipoCanonico.TEXTO: pa.string(), TipoCanonico.INTEIRO: pa.int64()}[tipo]


def _tabela_arrow(
    colunas: dict[str, Valores], esquema: EsquemaCanonico, decimais: dict[str, int]
) -> pa.Table:
    campos = [
        pa.field(c.nome, _tipo_arrow(c.tipo, decimais.get(c.nome, 0)), nullable=c.anulavel)
        for c in esquema.colunas
    ]
    return pa.table({c.nome: colunas[c.nome] for c in esquema.colunas}, schema=pa.schema(campos))


def _sem_duplicatas(
    colunas: dict[str, Valores], esquema: EsquemaCanonico
) -> tuple[dict[str, Valores], int]:
    nomes = [c.nome for c in esquema.colunas]
    linhas = list(zip(*(colunas[n] for n in nomes), strict=True))
    unicas = list(dict.fromkeys(linhas))
    posicoes = [nomes.index(n) for n in esquema.chave]
    chaves = {tuple(linha[p] for p in posicoes) for linha in unicas}
    if len(chaves) != len(unicas):
        raise _inesperado(f"chave_repetida schema={esquema.schema_id}")
    return {n: [linha[i] for linha in unicas] for i, n in enumerate(nomes)}, len(linhas) - len(
        unicas
    )


def conferir_anulaveis(colunas: dict[str, Valores], esquema: EsquemaCanonico) -> None:
    """Recusa nulo em coluna que o esquema declara não anulável."""
    raise NotImplementedError


def _conferir_competencia(colunas: dict[str, Valores], artifact: ArtifactVersion) -> None:
    competencia = artifact.chave.competencia_arquivo
    esperada = competencia.valor if competencia is not None else None
    divergentes = {valor for valor in colunas["dt_competencia"] if valor != esperada}
    if esperada is None or divergentes:
        raise _inesperado(
            f"competencia_divergente arquivo={esperada} lidas={sorted(map(str, divergentes))}"
        )


def _canonicas(
    artifact: ArtifactVersion, layout: LayoutSpec, brutos: bytes, conteudo: bytes
) -> tuple[dict[str, Valores], dict[str, int]]:
    pares = conferir_leiaute(ler_leiaute_zip(brutos), layout)
    recortes = fatiar(conteudo, [coluna for coluna, _ in pares])
    if not recortes[0]:
        raise _inesperado(f"tabela_vazia layout={layout.layout_id}")
    tabela = tabela_do_leiaute(layout)
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{TABELAS[tabela]}.yaml")
    colunas: dict[str, Valores] = {"artifact_id": [artifact.artifact_id] * len(recortes[0])}
    for (_, campo), valores in zip(pares, recortes, strict=True):
        colunas.update(_colunas_do_campo(valores, campo, esquema))
    _conferir_competencia(colunas, artifact)
    decimais = {campo.nome_canonico: campo.decimais for campo in layout.campos}
    return colunas, decimais


def _gravar(
    tabela: pa.Table, esquema: EsquemaCanonico, out: Path, artifact_id: str, runtime: RuntimeConfig
) -> tuple[str, str, Path]:
    """Grava o Parquet atomicamente e devolve (dataset_id, hash lógico, destino)."""
    nomes = [c.nome for c in esquema.colunas]
    with closing(conectar(runtime)) as con:
        con.register("arrow_sigtap", tabela)
        con.execute(f"CREATE TABLE {_TABELA_SQL} AS SELECT * FROM arrow_sigtap")  # noqa: S608
        hash_logico = hash_logico_relacao(con, _TABELA_SQL, nomes)
        dataset_id = calcular_dataset_id(esquema.schema_id, hash_logico, (artifact_id,))
        out.mkdir(parents=True, exist_ok=True)
        destino = out / f"{dataset_id}.parquet"
        temporario = destino.with_name(f".{destino.name}.tmp")
        con.table(_TABELA_SQL).write_parquet(str(temporario))
        temporario.replace(destino)
    return dataset_id, hash_logico, destino


def normalize_sigtap(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    out: Path,
    *,
    runtime: RuntimeConfig | None = None,
    origem_dados: OrigemDados = OrigemDados.REAL,
    limite_membro_bytes: int = LIMITE_MEMBRO_PADRAO,
) -> DatasetRef:
    """Normaliza uma tabela de um pacote TabelaUnificada do SIGTAP.

    Raises:
        QuarentenaLeitura: artefato não íntegro, zip ilegível, leiaute ausente ou incompatível,
            registro truncado, código fora do domínio, competência divergente ou tabela vazia.
        ArquivoAusente: conteúdo do artefato ou membro da tabela inexistente.
    """
    configuracao = runtime or RuntimeConfig()
    tabela = tabela_do_leiaute(layout)
    if tabela not in TABELAS:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_LEIAUTE, f"tabela_desconhecida tabela={tabela}"
        )
    esquema = EsquemaCanonico.de_yaml(ESQUEMAS / f"{TABELAS[tabela]}.yaml")
    dados = _bytes_do_artefato(artifact, configuracao)
    brutos, conteudo = _ler_tabela(artifact, dados, tabela, limite_membro_bytes)
    colunas, decimais = _canonicas(artifact, layout, brutos, conteudo)
    fisicos = len(colunas["artifact_id"])
    unicas, duplicatas = _sem_duplicatas(colunas, esquema)
    dataset_id, hash_logico, destino = _gravar(
        _tabela_arrow(unicas, esquema, decimais), esquema, out, artifact.artifact_id, configuracao
    )
    return _referencia(
        artifact,
        layout,
        (dataset_id, hash_logico, destino),
        (fisicos, duplicatas),
        schema_id=esquema.schema_id,
        origem_dados=origem_dados,
    )


def _referencia(
    artifact: ArtifactVersion,
    layout: LayoutSpec,
    gravado: tuple[str, str, Path],
    contagens: tuple[int, int],
    *,
    schema_id: str,
    origem_dados: OrigemDados,
) -> DatasetRef:
    dataset_id, hash_logico, destino = gravado
    fisicos, duplicatas = contagens
    tabela = tabela_do_leiaute(layout)
    linhas = fisicos - duplicatas
    logger.info(
        "sigtap_normalizado id=%s tabela=%s linhas=%s duplicatas=%s",
        artifact.artifact_id,
        tabela,
        linhas,
        duplicatas,
    )
    return DatasetRef(
        dataset_id=dataset_id,
        schema_id=schema_id,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=linhas,
        artifact_ids=(artifact.artifact_id,),
        origem_dados=origem_dados,
        produzido_por=(
            f"sustemporal.ingest.sigtap.normalize_sigtap/{layout.layout_id}"
            f"@{metadata.version('sus-temporal')}"
        ),
        reconciliacao=Reconciliacao(
            fisicos=fisicos,
            canonicas=linhas,
            excluidas_por_motivo={"duplicata_exata": duplicatas} if duplicatas else {},
        ),
        multiplicidade=Multiplicidade(
            linhas_totais=linhas, combinacoes_distintas=linhas, max_repeticoes=1
        ),
    )
