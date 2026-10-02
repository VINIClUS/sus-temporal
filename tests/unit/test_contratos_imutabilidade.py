import copy
from datetime import UTC, datetime

import pytest

from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import (
    Ambiente,
    BootstrapSpec,
    CodeVersion,
    CorrecaoMultiplicidade,
    FreezeManifest,
)
from tests.fixtures.sintetico.contratos import (
    dataset_sintetico,
    features_sinteticas,
    split_sintetico,
)

_SHA = "a" * 64


def _manifesto() -> FreezeManifest:
    return FreezeManifest.criar(
        criado_em=datetime(2026, 9, 1, tzinfo=UTC),
        config_hash=_SHA,
        codigo=CodeVersion(commit="c" * 40, sujo=False, versao_pacote="0.1.0"),
        ambiente=Ambiente(python="3.12.11", plataforma="linux", pacotes={"duckdb": "1.5.6"}),
        catalogos_sha256={"regras": _SHA},
        datasets=(dataset_sintetico(),),
        split=split_sintetico(),
        features=features_sinteticas(),
        bootstrap=BootstrapSpec(correcao=CorrecaoMultiplicidade.HOLM),
        metricas=("cobertura_rejeicoes",),
        comparacoes_primarias=("M_TEMP_x_B_ATEND",),
        margens={"M_TEMP_x_B_ATEND": "0.05"},
        decisao_g0="experiments/decisions/G0.yaml",
    )


def test_mapas_do_congelamento_nao_aceitam_mutacao() -> None:
    manifesto = _manifesto()
    with pytest.raises(TypeError):
        manifesto.catalogos_sha256["regras"] = "b" * 64
    with pytest.raises(TypeError):
        manifesto.margens.clear()
    with pytest.raises(TypeError):
        manifesto.ambiente.pacotes.update({"duckdb": "0.0.1"})
    with pytest.raises(TypeError):
        manifesto.catalogos_sha256 |= {"regras": "b" * 64}
    assert manifesto.catalogos_sha256 == {"regras": _SHA}


def test_mapa_da_config_nao_aceita_mutacao() -> None:
    config = RunConfig.model_validate({"versao": "1", "catalogos": {"regras": "catalog/rules"}})
    with pytest.raises(TypeError):
        config.catalogos["regras"] = "outro"
    with pytest.raises(TypeError):
        config.catalogos.setdefault("novo", "x")


def test_mapa_congelado_preserva_copia_serializacao_e_identidade() -> None:
    manifesto = _manifesto()
    assert copy.deepcopy(manifesto) == manifesto
    assert copy.copy(manifesto) == manifesto
    assert type(manifesto.model_dump()["catalogos_sha256"]) is dict
    assert FreezeManifest.model_validate(manifesto.model_dump(mode="json")) == manifesto
    assert manifesto.model_dump_json() == _manifesto().model_dump_json()
