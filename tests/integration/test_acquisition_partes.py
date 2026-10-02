"""Partes esperadas, terminador do DBF além da amostra e VERSAO sem OBSERVACAO; SINTETICO."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures.dbc_encoder import dbf_para_dbc
from tests.fixtures.dbf_writer import CampoDbf, escrever_dbf

from sustemporal import cli
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.manifest import Manifesto, ManifestoCorrompido
from sustemporal.acquisition.validation import validar_conteudo
from sustemporal.contracts.artifacts import (
    ChaveArtefato,
    EstadoIntegridade,
    FormatoArquivo,
    LinhaManifesto,
    MotivoRequisicao,
    SourceRequest,
    TipoLinhaManifesto,
    calcular_artifact_id,
)
from sustemporal.contracts.base import CanalPublicacao, FamiliaFonte
from sustemporal.errors import ExitCode

CATALOGO = Path("catalog/sources.yaml")


def _dbc(valor: str = "A") -> bytes:
    return dbf_para_dbc(escrever_dbf([CampoDbf("PA_X", "C", 1)], [(valor,)]))


def _ambiente(tmp_path: Path, partes_esperadas: str | None) -> Path:
    dados = tmp_path / "origem" / "SIASUS" / "200801_" / "Dados"
    dados.mkdir(parents=True)
    (dados / "PASP1801a.dbc").write_bytes(_dbc())
    texto = CATALOGO.read_text(encoding="utf-8").replace(
        "ftp://ftp.datasus.gov.br/dissemin/publicos", (tmp_path / "origem").as_uri()
    )
    if partes_esperadas is not None:
        texto = texto.replace(
            '    multipartes: "true"\n',
            f'    multipartes: "true"\n    partes_esperadas:\n      "201801": {partes_esperadas}\n',
            1,
        )
    catalogo = tmp_path / "sources.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    config = tmp_path / "config.yaml"
    linhas = [
        'versao: "1"',
        "runtime:",
        f"  raiz_dados: {tmp_path / 'data'}",
        f"  raiz_manifestos: {tmp_path / 'manifests'}",
        "piloto:",
        "  uf: SP",
        "  competencias_processamento: ['201801']",
        "  territorio: catalog/territorio/drs_xi.yaml",
        "  familias_fontes: [SIA_PA]",
        "catalogos:",
        f"  fontes: {catalogo}",
    ]
    config.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return config


def _linhas_de_log(capsys: pytest.CaptureFixture[str], evento: str) -> list[str]:
    return [linha for linha in capsys.readouterr().err.splitlines() if evento in linha]


def test_parte_declarada_e_nao_listada_torna_a_competencia_incompleta(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ambiente(tmp_path, "[a, b]")
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.FALHA_OPERACIONAL
    (aviso,) = _linhas_de_log(capsys, "partes_ausentes")
    assert " WARNING " in aviso
    assert "ausentes=b" in aviso


def test_sem_declaracao_registra_partes_listadas_e_completude_indeterminada(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _ambiente(tmp_path, None)
    assert cli.main(["acquire", "--config", str(config)]) == ExitCode.OK
    (registro,) = _linhas_de_log(capsys, "partes_listadas")
    assert "partes=a" in registro
    assert "completude=INDETERMINADA" in registro


def _dbf_com_cabecalho_grande(terminador: bytes) -> bytes:
    campos = [CampoDbf(f"C{i:03d}", "C", 1) for i in range(140)]
    dbf = bytearray(escrever_dbf(campos, [tuple("x" * 140)]))
    cabecalho = 32 + 32 * len(campos) + 1
    assert cabecalho > 4096
    dbf[cabecalho - 1] = terminador[0]
    return bytes(dbf)


@pytest.mark.parametrize(
    ("terminador", "estado"),
    [(b"\x0d", EstadoIntegridade.OK), (b"\x00", EstadoIntegridade.QUARENTENA_CONTEUDO_INESPERADO)],
)
@pytest.mark.parametrize("formato", [FormatoArquivo.DBF, FormatoArquivo.DBC])
def test_terminador_do_cabecalho_alem_da_amostra_e_conferido(
    tmp_path: Path, terminador: bytes, estado: EstadoIntegridade, formato: FormatoArquivo
) -> None:
    dbf = _dbf_com_cabecalho_grande(terminador)
    caminho = tmp_path / f"x.{formato.value.lower()}"
    caminho.write_bytes(dbf if formato is FormatoArquivo.DBF else dbf_para_dbc(dbf))
    assert validar_conteudo(caminho, formato).integridade is estado


def _requisicao(arquivo: Path) -> SourceRequest:
    chave = ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        uf="SP",
        competencia_arquivo="201801",
        parte="a",
        canal=CanalPublicacao.ATUAL,
        nome_original="PASP1801a.dbc",
    )
    return SourceRequest(
        chave=chave,
        localizador=arquivo.as_uri(),
        formato_esperado=FormatoArquivo.DBC,
        tamanho_maximo_bytes=1_000_000,
        motivo=MotivoRequisicao.PRIMARIA,
    )


def _versao_pendurada(store: Path) -> LinhaManifesto:
    caminho = store / "manifesto.jsonl"
    estado = Manifesto(caminho).ler()
    modelo = next(iter(estado.versoes.values()))
    sha256 = "e" * 64
    versao = modelo.model_copy(
        update={"sha256": sha256, "artifact_id": calcular_artifact_id(modelo.chave, sha256)}
    )
    ultima = estado.linhas[-1]
    linha = LinhaManifesto(
        sequencia=ultima.sequencia + 1,
        tipo=TipoLinhaManifesto.VERSAO,
        versao=versao,
        anterior_sha256=ultima.sha256(),
    )
    with caminho.open("a", encoding="utf-8") as arquivo:
        arquivo.write(linha.model_dump_json() + "\n")
    return linha


def test_versao_completa_sem_observacao_e_transacao_incompleta(tmp_path: Path) -> None:
    store = tmp_path / "store"
    origem = tmp_path / "a.dbc"
    origem.write_bytes(_dbc("A"))
    fetch_source(_requisicao(origem), store)
    pendurada = _versao_pendurada(store)
    with pytest.raises(ManifestoCorrompido, match="transacao_incompleta"):
        Manifesto(store / "manifesto.jsonl").ler()
    origem.write_bytes(_dbc("B"))
    observacao = fetch_source(_requisicao(origem), store)
    estado = Manifesto(store / "manifesto.jsonl").ler()
    assert estado.observacoes[-1] == observacao
    assert pendurada.versao is not None
    assert pendurada.versao.artifact_id not in estado.versoes
    (fragmento,) = store.glob("manifesto.jsonl.fragmento.*")
    assert pendurada.model_dump_json() in fragmento.read_text(encoding="utf-8")
