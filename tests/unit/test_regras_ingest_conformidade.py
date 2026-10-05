"""`validate --ingest`: toda entrada confere com o esquema e a seleção do T06 antes de gravar."""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sustemporal import cli
from sustemporal.config import load_config
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CompetenciaArquivo,
    EstadoSelecao,
    SelecaoVersao,
)
from sustemporal.errors import ConfigInvalida, ExitCode
from sustemporal.rules import ingest_selecao
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.conteudo import ConteudoDivergente
from sustemporal.rules.ingest import carregar_registro, ler_datasets, preparar_insumos_ingest
from sustemporal.rules.ingest_selecao import exigir_versao_selecionavel
from sustemporal.rules.validate_ingest import municipios_do_piloto
from sustemporal.temporal.registry import registro_de
from tests.fixtures.regras_cenario import reemitir
from tests.fixtures.regras_ingest import montar_ingest
from tests.fixtures.temporal_registro import ARTEFATO_PA, observar

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.records import DatasetRef
    from sustemporal.temporal.registry import RegistroTemporal
    from tests.fixtures.regras_ingest import MundoIngest

_PRODUCAO = "sia_pa.v1"
_ACEITAS = (EstadoSelecao.SELECIONADA, EstadoSelecao.INCOMPLETA)
_RECUSADAS = [estado for estado in EstadoSelecao if estado not in _ACEITAS]
# estados em que o seletor não traz artefato algum; a ambígua exige dois candidatos
_SEM_ARTEFATO = (EstadoSelecao.AUSENTE, EstadoSelecao.FORA_DO_CORTE, EstadoSelecao.NAO_RESOLVIDA)
# defeito injetado na produção → (coluna, motivo, linhas) do primeiro conjunto recusado
_DEFEITOS = {
    "deletado_nulo": ({"deletado_nulo": True}, ("deletado", "nulo", 1)),
    "sem_deletado": ({"sem_coluna_deletado": True}, ("deletado", "ausente", 3)),
    "sem_artifact_id": ({"sem_coluna_artifact_id": True}, ("artifact_id", "ausente", 3)),
}
# (esquema, coluna, motivo) adulterado no primeiro conjunto do esquema da pasta
_ADULTERACOES = {
    "producao_row_id_nulo": (_PRODUCAO, "row_id", "nulo"),
    "producao_indice_nulo": (_PRODUCAO, "indice_registro", "nulo"),
    "cnes_sem_vinculos": ("cnes_estab_cbo.v1", "n_vinculos", "ausente"),
    "sigtap_ocupacao_nula": ("sigtap_proc_ocupacao.v1", "co_ocupacao", "nulo"),
    "cobertura_sem_estado": ("cobertura.v1", "estado", "ausente"),
    "cobertura_estado_nulo": ("cobertura.v1", "estado", "nulo"),
}


def _recusa_ao_preparar(mundo: MundoIngest, destino: Path) -> ValueError:
    config = load_config(mundo.config)
    contexto = (config, carregar_registro(config), municipios_do_piloto(config))
    datasets = ler_datasets(mundo.pasta)
    with duckdb.connect() as con:
        try:
            preparar_insumos_ingest(con, datasets, carregar_regras(), contexto, destino)
        except ValueError as erro:
            return erro
    return pytest.fail("entrada_aceita_pela_preparacao")


def _validar(mundo: MundoIngest) -> int:
    argumentos = ["validate", "--config", str(mundo.config), "--policy", "processamento"]
    return cli.main([*argumentos, "--ingest", str(mundo.pasta), "--saida", str(mundo.saida)])


def _adulterar(mundo: MundoIngest, schema_id: str, coluna: str, motivo: str) -> DatasetRef:
    """Tira a coluna (ausente) ou anula a 1ª linha dela (nulo) no 1º conjunto do esquema."""
    refs = ler_datasets(mundo.pasta)
    posicao = next(i for i, ref in enumerate(refs) if ref.schema_id == schema_id)
    tabela = pq.read_table(refs[posicao].caminho)
    if motivo == "ausente":
        tabela = tabela.drop_columns([coluna])
    else:
        valores = tabela.column(coluna).to_pylist()
        valores[0] = None
        nova = pa.array(valores, tabela.schema.field(coluna).type)
        tabela = tabela.set_column(tabela.column_names.index(coluna), coluna, nova)
    pq.write_table(tabela, refs[posicao].caminho)
    refs[posicao] = reemitir(refs[posicao])
    linhas = "".join(f"{ref.model_dump_json()}\n" for ref in refs)
    (mundo.pasta / "datasets.jsonl").write_text(linhas, encoding="utf-8")
    return refs[posicao]


@pytest.mark.parametrize("caso", _DEFEITOS)
def test_producao_fora_do_esquema_e_recusada_antes_de_gravar(tmp_path: Path, caso: str) -> None:
    defeito, (coluna, motivo, linhas) = _DEFEITOS[caso]
    mundo = montar_ingest(tmp_path, **defeito)
    primeira = next(r for r in ler_datasets(mundo.pasta) if r.schema_id == _PRODUCAO)
    destino = tmp_path / "destino"
    erro = _recusa_ao_preparar(mundo, destino)
    assert isinstance(erro, ConteudoDivergente)
    assert str(erro) == (
        f"entrada_fora_do_esquema schema={_PRODUCAO} dataset={primeira.dataset_id} "
        f"coluna={coluna} motivo={motivo} linhas={linhas}"
    )
    assert not destino.exists()


@pytest.mark.parametrize("caso", _DEFEITOS)
def test_validate_ingest_com_producao_fora_do_esquema_sai_sem_saidas(
    tmp_path: Path, caso: str
) -> None:
    defeito, _ = _DEFEITOS[caso]
    mundo = montar_ingest(tmp_path, **defeito)
    assert _validar(mundo) == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


@pytest.mark.parametrize("caso", _ADULTERACOES)
def test_toda_coluna_obrigatoria_de_qualquer_conjunto_e_conferida_antes_de_gravar(
    tmp_path: Path, caso: str
) -> None:
    schema_id, coluna, motivo = _ADULTERACOES[caso]
    mundo = montar_ingest(tmp_path)
    ref = _adulterar(mundo, schema_id, coluna, motivo)
    destino = tmp_path / "destino"
    linhas = ref.linhas if motivo == "ausente" else 1
    erro = _recusa_ao_preparar(mundo, destino)
    assert isinstance(erro, ConteudoDivergente)
    assert str(erro) == (
        f"entrada_fora_do_esquema schema={schema_id} dataset={ref.dataset_id} "
        f"coluna={coluna} motivo={motivo} linhas={linhas}"
    )
    assert not destino.exists()


def test_producao_em_quarentena_e_recusada_antes_de_gravar(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, producao_em_quarentena=True)
    destino = tmp_path / "destino"
    erro = _recusa_ao_preparar(mundo, destino)
    assert isinstance(erro, ConteudoDivergente)
    assert str(erro) == (
        "producao_com_selecao_nao_aceita competencia=202302 estado=EM_QUARENTENA "
        "motivo=conteudo_em_quarentena fonte=SIA_PA competencia=202302"
    )
    assert not destino.exists()


def test_validate_ingest_com_producao_em_quarentena_sai_sem_saidas(tmp_path: Path) -> None:
    mundo = montar_ingest(tmp_path, producao_em_quarentena=True)
    assert _validar(mundo) == ExitCode.CONFIG_INVALIDA
    assert not mundo.saida.exists() or not any(mundo.saida.rglob("*"))


def _com_selecao(
    monkeypatch: pytest.MonkeyPatch, estado: EstadoSelecao
) -> tuple[list[str], RegistroTemporal, RunConfig, SelecaoVersao]:
    """Registro de uma versão do SIA-PA de 202302 cuja seleção do T06 sai no estado dado."""
    observacao, versao = observar(FamiliaFonte.SIA_PA, "202302", "pa-a", 1, parte="a")
    assert versao is not None
    artefatos = () if estado in _SEM_ARTEFATO else (versao.artifact_id,)
    if estado is EstadoSelecao.AMBIGUA:
        artefatos = (versao.artifact_id, ARTEFATO_PA)
    selecao = SelecaoVersao(
        fonte=FamiliaFonte.SIA_PA,
        base=BaseTemporal.PROCESSAMENTO,
        competencia_requerida=CompetenciaArquivo("202302"),
        estado=estado,
        artifact_ids=artefatos,
        motivo="sintetico",
    )
    monkeypatch.setattr(ingest_selecao, "selecionar_versao", lambda *_, **__: selecao)
    piloto = {
        "uf": "SP",
        "competencias_processamento": ["202302"],
        "territorio": "catalog/territorio/drs_xi.yaml",
        "familias_fontes": ["SIA_PA"],
    }
    config = RunConfig.model_validate({"versao": "1", "piloto": piloto})
    return [versao.artifact_id], registro_de([observacao], [versao]), config, selecao


@pytest.mark.parametrize("estado", _ACEITAS)
def test_selecao_completa_ou_incompleta_e_aceita_para_a_producao(
    monkeypatch: pytest.MonkeyPatch, estado: EstadoSelecao
) -> None:
    artefatos, registro, config, selecao = _com_selecao(monkeypatch, estado)
    incompletas = exigir_versao_selecionavel(artefatos, registro, config)
    assert incompletas == ({"202302": selecao} if estado is EstadoSelecao.INCOMPLETA else {})


@pytest.mark.parametrize("estado", _RECUSADAS)
def test_qualquer_outro_estado_de_selecao_e_recusado_para_a_producao(
    monkeypatch: pytest.MonkeyPatch, estado: EstadoSelecao
) -> None:
    artefatos, registro, config, _ = _com_selecao(monkeypatch, estado)
    with pytest.raises((ConfigInvalida, ConteudoDivergente)) as erro:
        exigir_versao_selecionavel(artefatos, registro, config)
    assert type(erro.value) is ConteudoDivergente
    assert str(erro.value) == (
        f"producao_com_selecao_nao_aceita competencia=202302 estado={estado} motivo=sintetico"
    )
