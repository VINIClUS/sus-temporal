from pathlib import Path

import pytest

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import Portao
from sustemporal.errors import PortaoRecusado
from sustemporal.gates import carregar_decisoes, exigir_confirmatorio_valido, exigir_portao

FREEZE = "frz_" + "a" * 64


def _decisao(diretorio: Path, nome: str, conteudo: str) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / nome).write_text(conteudo, encoding="utf-8")


G0_CONTINUAR = (
    "portao: G0\ndecisao: CONTINUAR\ndata: 2027-01-15\nresponsaveis: [orientacao]\n"
    "registrado_por_humano: true\n"
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
    _decisao(
        tmp_path,
        "g2.yaml",
        "portao: G2\ndecisao: ABRIR_TESTE\ndata: 2027-06-01\nresponsaveis: [orientacao]\n"
        f"registrado_por_humano: true\nfreeze_id: {outro}\n",
    )
    with pytest.raises(PortaoRecusado):
        exigir_portao(tmp_path, Portao.G2, freeze_id=FREEZE)
    assert exigir_portao(tmp_path, Portao.G2, freeze_id=outro).freeze_id == outro


def test_confirmatorio_com_sintetico_e_recusado(tmp_path: Path) -> None:
    config = RunConfig.model_validate(
        {
            "versao": "1",
            "modo": "CONFIRMATORIO",
            "origem_dados": "REAL",
            "freeze_id": FREEZE,
            "bootstrap": {"correcao": "HOLM"},
            "runtime": {"dir_decisoes": str(tmp_path)},
        }
    )
    with pytest.raises(PortaoRecusado):
        exigir_confirmatorio_valido(config, OrigemDados.SINTETICO)
    with pytest.raises(PortaoRecusado):
        exigir_confirmatorio_valido(config, OrigemDados.REAL)
