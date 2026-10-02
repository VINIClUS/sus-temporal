import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from sustemporal import gates
from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.contracts.experiment import Portao
from sustemporal.errors import PortaoRecusado
from sustemporal.gates import carregar_decisoes, exigir_confirmatorio_valido, exigir_portao

FREEZE = "frz_" + "a" * 64


def _decisao(diretorio: Path, nome: str, conteudo: str) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / nome).write_text(conteudo, encoding="utf-8")


G0_CONTINUAR = (
    "portao: G0\ndecisao: CONTINUAR\ndata: 2025-01-15\nresponsaveis: [orientacao]\n"
    "registrado_por_humano: true\n"
)
G2_ABRIR = (
    "portao: G2\ndecisao: ABRIR_TESTE\ndata: 2025-06-01\nresponsaveis: [orientacao]\n"
    f"registrado_por_humano: true\nfreeze_id: {FREEZE}\n"
)


def _config_confirmatoria() -> RunConfig:
    return RunConfig.model_validate(
        {
            "versao": "1",
            "modo": "CONFIRMATORIO",
            "origem_dados": "REAL",
            "freeze_id": FREEZE,
            "bootstrap": {"correcao": "HOLM"},
        }
    )


def test_sem_decisao_registrada_recusa_portao(tmp_path: Path) -> None:
    with pytest.raises(PortaoRecusado):
        exigir_portao(tmp_path / "decisions", Portao.G0)


def test_decisao_humana_libera_portao(tmp_path: Path) -> None:
    _decisao(tmp_path, "g0.yaml", G0_CONTINUAR)
    assert exigir_portao(tmp_path, Portao.G0).decisao == "CONTINUAR"


def test_reformular_nao_libera_g0(tmp_path: Path) -> None:
    _decisao(tmp_path, "g0.yaml", G0_CONTINUAR.replace("CONTINUAR", "REFORMULAR"))
    with pytest.raises(PortaoRecusado):
        exigir_portao(tmp_path, Portao.G0)


def test_modelo_de_decisao_e_ignorado(tmp_path: Path) -> None:
    _decisao(tmp_path, "MODELO_G0.yaml", G0_CONTINUAR)
    assert carregar_decisoes(tmp_path, Portao.G0) == []


def test_decisao_sem_registro_humano_recusa(tmp_path: Path) -> None:
    _decisao(tmp_path, "g0.yaml", G0_CONTINUAR.replace("true", "false"))
    with pytest.raises(PortaoRecusado):
        exigir_portao(tmp_path, Portao.G0)


def test_g2_exige_o_mesmo_congelamento(tmp_path: Path) -> None:
    outro = "frz_" + "b" * 64
    _decisao(tmp_path, "g2.yaml", G2_ABRIR.replace(FREEZE, outro))
    with pytest.raises(PortaoRecusado):
        exigir_portao(tmp_path, Portao.G2, freeze_id=FREEZE)
    assert exigir_portao(tmp_path, Portao.G2, freeze_id=outro).freeze_id == outro


def test_confirmatorio_com_sintetico_e_recusado(tmp_path: Path) -> None:
    assert "diretorio" in inspect.signature(exigir_confirmatorio_valido).parameters
    config = _config_confirmatoria()
    with pytest.raises(PortaoRecusado):
        exigir_confirmatorio_valido(config, OrigemDados.SINTETICO, diretorio=tmp_path)
    with pytest.raises(PortaoRecusado):
        exigir_confirmatorio_valido(config, OrigemDados.REAL, diretorio=tmp_path)


def test_confirmatorio_com_g2_do_congelamento_e_liberado(tmp_path: Path) -> None:
    assert "hoje" in inspect.signature(exigir_confirmatorio_valido).parameters
    _decisao(tmp_path, "g2.yaml", G2_ABRIR)
    config = _config_confirmatoria()
    exigir_confirmatorio_valido(config, OrigemDados.REAL, diretorio=tmp_path, hoje=date(2025, 6, 1))
    with pytest.raises(PortaoRecusado, match="decisao_no_futuro"):
        exigir_confirmatorio_valido(
            config, OrigemDados.REAL, diretorio=tmp_path, hoje=date(2025, 5, 31)
        )


def test_diretorio_de_decisoes_e_fixo_e_nao_configuravel() -> None:
    assert "dir_decisoes" not in RuntimeConfig.model_fields
    assert "dir_congelamentos" in RuntimeConfig.model_fields
    assert getattr(gates, "DIR_DECISOES", None) == Path("experiments/decisions")
    parametro = inspect.signature(exigir_confirmatorio_valido).parameters.get("diretorio")
    assert parametro is not None
    assert parametro.kind is inspect.Parameter.KEYWORD_ONLY
    assert parametro.default == Path("experiments/decisions")


def test_decisao_posterior_que_nao_libera_prevalece(tmp_path: Path) -> None:
    _decisao(tmp_path, "g0_1.yaml", G0_CONTINUAR)
    reformular = G0_CONTINUAR.replace("CONTINUAR", "REFORMULAR").replace("2025-01-15", "2025-02-01")
    _decisao(tmp_path, "g0_2.yaml", reformular)
    with pytest.raises(PortaoRecusado, match="portao_ultima_decisao_nao_libera"):
        exigir_portao(tmp_path, Portao.G0)


def test_decisoes_divergentes_na_data_mais_recente_recusam(tmp_path: Path) -> None:
    _decisao(tmp_path, "g0_1.yaml", G0_CONTINUAR)
    _decisao(tmp_path, "g0_2.yaml", G0_CONTINUAR.replace("CONTINUAR", "REFORMULAR"))
    with pytest.raises(PortaoRecusado, match="portao_decisoes_empatadas"):
        exigir_portao(tmp_path, Portao.G0)


def test_g2_adiado_depois_de_aberto_recusa_o_mesmo_congelamento(tmp_path: Path) -> None:
    _decisao(tmp_path, "g2_1.yaml", G2_ABRIR)
    adiar = G2_ABRIR.replace("ABRIR_TESTE", "ADIAR").replace("2025-06-01", "2025-06-10")
    _decisao(tmp_path, "g2_2.yaml", adiar)
    with pytest.raises(PortaoRecusado, match="portao_ultima_decisao_nao_libera"):
        exigir_portao(tmp_path, Portao.G2, freeze_id=FREEZE)


@pytest.mark.parametrize("conteudo", ["portao: [G0\n", "portao: G0\n\x07\n"])
def test_decisao_ilegivel_recusa_portao(tmp_path: Path, conteudo: str) -> None:
    _decisao(tmp_path, "g0.yaml", conteudo)
    with pytest.raises(PortaoRecusado, match="decisao_invalida"):
        exigir_portao(tmp_path, Portao.G0)


def test_g2_sem_freeze_id_e_recusado(tmp_path: Path) -> None:
    _decisao(tmp_path, "g2.yaml", G2_ABRIR)
    with pytest.raises(PortaoRecusado, match="portao_g2_exige_freeze_id"):
        exigir_portao(tmp_path, Portao.G2)


def test_decisao_com_data_futura_recusa_portao(tmp_path: Path) -> None:
    assert "hoje" in inspect.signature(exigir_portao).parameters
    _decisao(tmp_path, "g0.yaml", G0_CONTINUAR)
    assert exigir_portao(tmp_path, Portao.G0, hoje=date(2025, 1, 15)).decisao == "CONTINUAR"
    with pytest.raises(PortaoRecusado, match="decisao_no_futuro"):
        exigir_portao(tmp_path, Portao.G0, hoje=date(2025, 1, 14))


def test_hoje_padrao_e_a_data_utc_do_relogio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _RelogioFixo(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz is UTC
            return datetime(2025, 1, 14, 23, 59, tzinfo=UTC)

    monkeypatch.setattr(gates, "datetime", _RelogioFixo, raising=False)
    _decisao(tmp_path, "g0.yaml", G0_CONTINUAR)
    with pytest.raises(PortaoRecusado, match="decisao_no_futuro"):
        exigir_portao(tmp_path, Portao.G0)


def test_decisao_em_arquivo_yml_e_lida(tmp_path: Path) -> None:
    _decisao(tmp_path, "g0.yml", G0_CONTINUAR)
    assert [decisao.decisao for decisao in carregar_decisoes(tmp_path, Portao.G0)] == ["CONTINUAR"]


def test_diretorio_de_decisoes_em_link_simbolico_e_recusado(tmp_path: Path) -> None:
    _decisao(tmp_path / "real", "g0.yaml", G0_CONTINUAR)
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(PortaoRecusado, match="decisoes_em_link_simbolico"):
        exigir_portao(tmp_path / "link", Portao.G0)


@pytest.mark.parametrize("nome", ["g0.yaml", "g0.yml"])
def test_arquivo_de_decisao_em_link_simbolico_e_recusado(tmp_path: Path, nome: str) -> None:
    externo = tmp_path / "externo.yaml"
    externo.write_text(G0_CONTINUAR, encoding="utf-8")
    decisoes = tmp_path / "decisions"
    decisoes.mkdir()
    (decisoes / nome).symlink_to(externo)
    with pytest.raises(PortaoRecusado, match="decisoes_em_link_simbolico"):
        carregar_decisoes(decisoes, Portao.G0)


def test_ancestral_relativo_em_link_simbolico_e_recusado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _decisao(tmp_path / "real" / "decisions", "g0.yaml", G0_CONTINUAR)
    (tmp_path / "experiments").symlink_to(tmp_path / "real", target_is_directory=True)
    assert len(carregar_decisoes(tmp_path / "experiments" / "decisions", Portao.G0)) == 1
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PortaoRecusado, match="decisoes_em_link_simbolico"):
        carregar_decisoes(Path("experiments/decisions"), Portao.G0)
