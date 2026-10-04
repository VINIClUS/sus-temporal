"""Leitura conferida de um DBC/DBF do CNES: integridade, endereço, fidelidade e leiaute estrito.

Segue o padrão do SIA-PA (ADR 0002): caminho derivado do sha256 dentro de `raiz_dados`,
descompressão com teto, verificação de fidelidade e leiaute conferido por nome, ordem, tipo,
largura e decimais; divergência vai para quarentena, nunca para leitura aproximada.
"""

from __future__ import annotations

import codecs
import hashlib
import tempfile
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts import (
    EstadoIntegridade,
    FormatoArquivo,
    FormatoLeiaute,
    RuntimeConfig,
    calcular_dataset_id,
)
from sustemporal.duck import conectar
from sustemporal.hashing import hash_logico_relacao
from sustemporal.ingest.dbc import ler_dbc_arquivo, verificar_fidelidade
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura, compactar, ler_dbf_arquivo
from sustemporal.store import caminho_conteudo

if TYPE_CHECKING:
    import pyarrow as pa

    from sustemporal.contracts import ArtifactVersion, EsquemaCanonico, LayoutSpec
    from sustemporal.ingest.dbf import CabecalhoDbf, LeituraDbf

__all__ = ["conferir_leiaute_dbf", "gravar_relacao", "ler_artefato_dbf"]

_EXTENSOES = {FormatoArquivo.DBC: "dbc", FormatoArquivo.DBF: "dbf"}


def _leiaute(motivo: str) -> QuarentenaLeitura:
    return QuarentenaLeitura(EstadoIntegridade.QUARENTENA_LEIAUTE, motivo)


def _latin1(codificacao: str) -> bool:
    try:
        return codecs.lookup(codificacao).name == "iso8859-1"
    except LookupError:
        return False


def _conferir_declarado(artifact: ArtifactVersion, layout: LayoutSpec) -> None:
    if layout.formato is not FormatoLeiaute.DBF or not _latin1(layout.codificacao):
        raise _leiaute(f"leiaute_nao_dbf_latin1 layout={layout.layout_id}")
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


def conferir_leiaute_dbf(cabecalho: CabecalhoDbf, layout: LayoutSpec) -> None:
    """Mesmos campos e ordem do catálogo, com tipo, largura e decimais iguais.

    Campos com `obrigatorio` falso podem faltar; os presentes seguem a ordem do catálogo.

    Raises:
        QuarentenaLeitura: campo ausente, extra, fora de ordem ou com descritor divergente.
    """
    presentes = {campo.nome for campo in cabecalho.campos}
    esperados = [c for c in layout.campos if c.obrigatorio or c.nome_fisico in presentes]
    lidos = [campo.nome for campo in cabecalho.campos]
    if lidos != [c.nome_fisico for c in esperados]:
        raise _leiaute(f"campos_divergentes layout={layout.layout_id} lidos={compactar(lidos)}")
    for lido, esperado in zip(cabecalho.campos, esperados, strict=True):
        fisico = (lido.tipo, lido.largura, lido.decimais)
        alvo = (esperado.tipo_fisico, esperado.largura, esperado.decimais)
        if fisico != alvo:
            raise _leiaute(
                f"descritor_divergente campo={lido.nome} lido={compactar(fisico)} "
                f"esperado={compactar(alvo)}"
            )


def _caminho_seguro(artifact: ArtifactVersion, raiz_dados: Path) -> Path:
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


def _bytes(artifact: ArtifactVersion, runtime: RuntimeConfig) -> bytes:
    if artifact.integridade is not EstadoIntegridade.OK:
        raise QuarentenaLeitura(
            artifact.integridade, f"artefato_nao_integro id={artifact.artifact_id}"
        )
    caminho = _caminho_seguro(artifact, Path(runtime.raiz_dados))
    if not caminho.is_file():
        raise ArquivoAusente(f"arquivo_ausente id={artifact.artifact_id}")
    dados = caminho.read_bytes()
    if hashlib.sha256(dados).hexdigest() != artifact.sha256:
        raise QuarentenaLeitura(
            EstadoIntegridade.QUARENTENA_CHECKSUM, f"sha256_divergente id={artifact.artifact_id}"
        )
    return dados


def ler_artefato_dbf(
    artifact: ArtifactVersion, layout: LayoutSpec, runtime: RuntimeConfig
) -> LeituraDbf:
    """Lê os bytes uma vez, descomprime com teto, verifica fidelidade e confere o leiaute.

    Raises:
        QuarentenaLeitura: artefato não íntegro, caminho inseguro, checksum, leitura reprovada ou
            leiaute incompatível.
        ArquivoAusente: conteúdo do artefato inexistente.
    """
    _conferir_declarado(artifact, layout)
    dados = _bytes(artifact, runtime)
    with tempfile.TemporaryDirectory() as nome_pasta:
        copia = Path(nome_pasta) / f"artefato.{_EXTENSOES[artifact.formato]}"
        copia.write_bytes(dados)
        if artifact.formato is FormatoArquivo.DBF:
            leitura = ler_dbf_arquivo(copia)
        else:
            leitura = ler_dbc_arquivo(copia, dir_temporario=Path(nome_pasta)).leitura
    modo = runtime.verificacao_fidelidade
    if artifact.formato is FormatoArquivo.DBC and modo != "DESLIGADA":
        relatorio = verificar_fidelidade(dados, leitura, modo)
        if not relatorio.fiel:
            raise QuarentenaLeitura(
                EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO,
                f"fidelidade_reprovada divergencias={compactar(list(relatorio.divergencias))}",
            )
    conferir_leiaute_dbf(leitura.cabecalho, layout)
    return leitura


def gravar_relacao(
    tabela: pa.Table,
    esquema: EsquemaCanonico,
    out: Path,
    artifact_id: str,
    runtime: RuntimeConfig,
) -> tuple[str, str, Path]:
    """Grava o Parquet atomicamente e devolve (dataset_id, hash lógico, destino)."""
    nomes = [c.nome for c in esquema.colunas]
    with closing(conectar(runtime)) as con:
        con.register("arrow_cnes", tabela)
        con.execute("CREATE TABLE cnes AS SELECT * FROM arrow_cnes")
        hash_logico = hash_logico_relacao(con, "cnes", nomes)
        dataset_id = calcular_dataset_id(esquema.schema_id, hash_logico, (artifact_id,))
        out.mkdir(parents=True, exist_ok=True)
        destino = out / f"{dataset_id}.parquet"
        temporario = destino.with_name(f".{destino.name}.tmp")
        con.table("cnes").write_parquet(str(temporario))
        temporario.replace(destino)
    return dataset_id, hash_logico, destino
