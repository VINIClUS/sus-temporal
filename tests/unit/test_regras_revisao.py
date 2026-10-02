"""Achados da revisão adversarial interna do T07 (cenários SINTETICOS)."""

from pathlib import Path

import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.temporal import (
    BaseTemporal,
    CriterioTemporal,
    MetodoId,
    PoliticaTemporal,
    TipoPolitica,
)
from sustemporal.rules.catalog import CATALOGO_REGRAS, CatalogoInvalido, carregar_regras
from sustemporal.rules.engine import evaluate_rules
from tests.fixtures.regras_cenario import CenarioRegras, materializar, snapshot_vazio
from tests.fixtures.regras_execucao import avaliacoes_por_chave, executar
from tests.fixtures.regras_exemplos import (
    ART_CNES,
    ART_SIA,
    ART_SIGTAP,
    COMPETENCIA,
    REGRAS,
    artefato_sigtap_vazio,
    cenario_base,
    registro,
    selecao,
)

LINHA = registro()["row_id"]
_SIGTAP = {"artifact_id": ART_SIGTAP, "dt_competencia": COMPETENCIA}


def _com_linha(cenario: CenarioRegras, schema_id: str, linha: dict[str, object]) -> CenarioRegras:
    auxiliares = dict(cenario.auxiliares)
    auxiliares[schema_id] = (*auxiliares[schema_id], linha)
    return cenario.com(auxiliares=auxiliares)


@pytest.mark.parametrize(
    ("regra", "linha_registro", "schema_id", "linha_auxiliar"),
    [
        (
            "PROC_CBO_SIGTAP",
            {"cbo": "999999"},
            "sigtap_proc_ocupacao.v1",
            _SIGTAP | {"co_procedimento": "0301010072", "co_ocupacao": None},
        ),
        (
            "PROC_CBO_SIGTAP",
            {"cbo": "999999"},
            "sigtap_proc_ocupacao.v1",
            _SIGTAP | {"co_procedimento": None, "co_ocupacao": "999999"},
        ),
        (
            "ESTAB_CBO_CNES",
            {"cbo": "999999"},
            "cnes_estab_cbo.v1",
            {
                "artifact_id": ART_CNES,
                "competencia_arquivo": COMPETENCIA,
                "cnes": "1234567",
                "cbo": None,
                "n_vinculos": 1,
            },
        ),
        (
            "INSTRUMENTO_REGISTRO_SIGTAP",
            {"instrumento": "I"},
            "sigtap_proc_registro.v1",
            _SIGTAP | {"co_procedimento": "0301010072", "co_registro": None},
        ),
        (
            "VIGENCIA_PROCEDIMENTO_SIGTAP",
            {"procedimento": "0202020202"},
            "sigtap_procedimento.v1",
            _SIGTAP | {"co_procedimento": None},
        ),
    ],
)
def test_chave_nula_na_fonte_auxiliar_nunca_vira_violacao(
    tmp_path: Path,
    regra: str,
    linha_registro: dict[str, str],
    schema_id: str,
    linha_auxiliar: dict[str, object],
) -> None:
    cenario = _com_linha(cenario_base(registro(**linha_registro)), schema_id, linha_auxiliar)
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, regra)]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "CAMPO_INSUFICIENTE")


@pytest.mark.parametrize("cbo", ["", "      ", "22512", "2251255"])
def test_codigo_fora_do_padrao_conta_como_nulo(tmp_path: Path, cbo: str) -> None:
    avaliacoes = avaliacoes_por_chave(executar(tmp_path, cenario_base(registro(cbo=cbo))))
    for regra in ("PROC_CBO_SIGTAP", "ESTAB_CBO_CNES"):
        assert (avaliacoes[(LINHA, regra)]["estado"], avaliacoes[(LINHA, regra)]["motivos"]) == (
            "INCONCLUSIVO",
            "CAMPO_INSUFICIENTE",
        )


def test_registro_de_versao_sia_em_quarentena_e_inconclusivo(tmp_path: Path) -> None:
    cenario = cenario_base(registro(cbo="999999"))
    cenario = cenario.com(
        integridade=cenario.integridade | {ART_SIA: EstadoIntegridade.QUARENTENA_TRUNCADO}
    )
    avaliacoes = avaliacoes_por_chave(executar(tmp_path, cenario))
    for regra in REGRAS:
        assert avaliacoes[(LINHA, regra)]["estado"] == "INCONCLUSIVO"
        assert "ARQUIVO_EM_QUARENTENA" in avaliacoes[(LINHA, regra)]["motivos"]


def test_ausencia_exige_linhas_em_todas_as_versoes_selecionadas(tmp_path: Path) -> None:
    vazio = artefato_sigtap_vazio()
    cenario = cenario_base(registro(cbo="999999"))
    selecoes = tuple(
        selecao(str(s["row_id"]), str(s["rule_id"]), artefatos=f"{ART_SIGTAP};{vazio}")
        if s["rule_id"] == "PROC_CBO_SIGTAP"
        else s
        for s in cenario.selecoes
    )
    registrados = {"sigtap_proc_ocupacao.v1": (ART_SIGTAP, vazio)}
    integridade = cenario.integridade | {vazio: EstadoIntegridade.OK}
    cenario = cenario.com(
        selecoes=selecoes, artefatos_auxiliar=registrados, integridade=integridade
    )
    avaliacao = avaliacoes_por_chave(executar(tmp_path, cenario))[(LINHA, "PROC_CBO_SIGTAP")]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "COBERTURA_INSUFICIENTE")


def test_motor_recusa_conjunto_que_nao_e_sia_pa(tmp_path: Path) -> None:
    dataset, insumos = materializar(cenario_base(), tmp_path / "entrada")
    auxiliar = insumos.auxiliares[0]
    with pytest.raises(ValueError, match="conjunto_de_registros_invalido"):
        evaluate_rules(
            auxiliar,
            snapshot_vazio(),
            carregar_regras(),
            RunConfig(versao="1"),
            tmp_path / "s",
            insumos=insumos,
        )
    assert dataset.schema_id == "sia_pa.v1"


def test_competencia_invalida_com_deslocamento_nao_derruba_a_execucao(tmp_path: Path) -> None:
    politica = PoliticaTemporal(
        politica_id="deslocada_sintetica",
        tipo=TipoPolitica.ALTERNATIVA_EXPLORATORIA,
        metodo=MetodoId.M_TEMP,
        criterios=tuple(
            CriterioTemporal(fonte=f, base=BaseTemporal.ATENDIMENTO, deslocamento_meses=-1)
            for f in (FamiliaFonte.CNES_PF, FamiliaFonte.SIGTAP)
        ),
    )
    cenario = cenario_base(registro(0), registro(1, competencia_atendimento="202013"))
    resultado = executar(tmp_path, cenario.com(politica=politica), derivar_selecao=True)
    assert resultado.falhas == 0
    avaliacao = avaliacoes_por_chave(resultado)[(registro(1)["row_id"], "PROC_CBO_SIGTAP")]
    assert (avaliacao["estado"], avaliacao["motivos"]) == ("INCONCLUSIVO", "VIGENCIA_NAO_RESOLVIDA")


def test_catalogo_exige_as_colunas_do_predicado_da_familia(tmp_path: Path) -> None:
    raiz = tmp_path / "rules"
    for origem in CATALOGO_REGRAS.rglob("*.yaml"):
        alvo = raiz / origem.relative_to(CATALOGO_REGRAS)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(origem.read_text(encoding="utf-8"), encoding="utf-8")
    alvo = next(raiz.rglob("ESTAB_CBO_CNES.yaml"))
    alvo.write_text(
        alvo.read_text(encoding="utf-8").replace(
            "campos_necessarios: [instrumento, cnes, cbo]",
            "campos_necessarios: [instrumento, cnes]",
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogoInvalido, match="campos_do_predicado"):
        carregar_regras(raiz)
