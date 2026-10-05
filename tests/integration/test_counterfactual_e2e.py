"""E2E: `sustemporal validate` real e `sustemporal counterfactual` real sobre a mesma execução.

Entrada SINTETICA, sem rede e sem mock do motor: o `validate` grava as saídas e o
`entrada_validacao.json`, e o `counterfactual` lê só a pasta dessa execução. Nada aqui é
resultado empírico: as hipóteses vêm do catálogo fechado e nunca asseguram aprovação.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from tests.fixtures.contrafactual_e2e import (
    ChamadaMotor,
    ExecucaoReal,
    espiar_motor,
    instantaneo,
    validar_entrada_pela_cli,
    validar_ingest_pela_cli,
)
from tests.fixtures.regras_cenario import politica

from sustemporal import cli
from sustemporal.contracts.counterfactual import (
    CounterfactualSearchResult,
    Executabilidade,
    Minimalidade,
    MotivoParada,
)
from sustemporal.contracts.temporal import MetodoId
from sustemporal.explanation.counterfactual_operacoes import (
    CATALOGO_OPERACOES,
    carregar_operacoes,
)
from sustemporal.rules.catalog import carregar_regras
from sustemporal.rules.insumos import politica_padrao

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_ESTAB_CBO = "ESTAB_CBO_CNES"


@pytest.fixture(autouse=True)
def _log_isolado() -> Iterator[None]:
    """`cli.main` reconfigura o log da raiz; o handler dele não sobrevive ao teste."""
    raiz = logging.getLogger()
    antes, nivel = list(raiz.handlers), raiz.level
    yield
    for handler in [h for h in raiz.handlers if h not in antes]:
        raiz.removeHandler(handler)
    raiz.setLevel(nivel)


@dataclass(frozen=True)
class _Publicado:
    resultado: CounterfactualSearchResult
    bruto: dict[str, Any]
    identidade: dict[str, Any]


def _contrafactual(execucao: ExecucaoReal, row: str) -> int:
    argumentos = ["counterfactual", "--config", str(execucao.config)]
    return cli.main([*argumentos, "--run", execucao.run_id, "--row", row])


def _publicado(execucao: ExecucaoReal) -> _Publicado:
    """O único resultado publicado pela execução e a `identidade.json` ao lado dele."""
    (caminho,) = execucao.contrafactuais.rglob("contrafactual.json")
    texto = caminho.read_text(encoding="utf-8")
    identidade = json.loads((caminho.parent / "identidade.json").read_text(encoding="utf-8"))
    resultado = CounterfactualSearchResult.model_validate_json(texto)
    return _Publicado(resultado, json.loads(texto), identidade)


def _reavaliou_no_motor(chamadas: list[ChamadaMotor], row: str, alvos: set[str]) -> None:
    """O motor reproduziu a violação no estado observado, e só ele disse `CONFORME` no candidato."""
    observadas = [c for c in chamadas if not c.sobreposta]
    sobrepostas = [c for c in chamadas if c.sobreposta]
    assert observadas
    assert all(c.estados[(row, r)] == "VIOLACAO" for c in observadas for r in alvos)
    assert sobrepostas
    assert any(all(c.estados[(row, r)] == "CONFORME" for r in alvos) for c in sobrepostas)


def test_entrada_real_violacao_ganha_hipotese_do_catalogo_revalidada_no_motor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execucao = validar_entrada_pela_cli(tmp_path)
    linha = execucao.linha_com_violacao()
    alvos = execucao.regras_em(linha, "VIOLACAO")
    antes = instantaneo(tmp_path, sem=execucao.contrafactuais)
    chamadas = espiar_motor(monkeypatch)

    assert _contrafactual(execucao, linha) == 0

    publicado = _publicado(execucao)
    resultado = publicado.resultado
    assert set(resultado.regras_alvo) == alvos == {_ESTAB_CBO}
    assert resultado.solucoes
    assert resultado.candidatos_avaliados >= 1
    catalogo = {operacao.op_id for operacao in carregar_operacoes()}
    for solucao in resultado.solucoes:
        assert {operacao.op_id for operacao in solucao.operacoes} <= catalogo
        assert solucao.resolve_alvo
        assert not solucao.novas_violacoes
        assert alvos <= set(solucao.regras_revalidadas)
        assert solucao.executabilidade is Executabilidade.HIPOTESE_PASSADA
    assert resultado.aprovacao_garantida is False
    assert publicado.bruto["aprovacao_garantida"] is False
    _reavaliou_no_motor(chamadas, linha, alvos)
    sha256 = hashlib.sha256(CATALOGO_OPERACOES.read_bytes()).hexdigest()
    assert publicado.identidade["catalogo_operacoes_sha256"] == sha256
    assert instantaneo(tmp_path, sem=execucao.contrafactuais) == antes


def test_entrada_real_com_politica_explicita_e_reproduzida_pelo_contexto(tmp_path: Path) -> None:
    explicita = politica(MetodoId.B_ATEND)
    assert explicita.politica_id != politica_padrao(MetodoId.B_ATEND, carregar_regras()).politica_id
    execucao = validar_entrada_pela_cli(tmp_path, politica=explicita)
    assert execucao.politica_id == explicita.politica_id
    linha = execucao.linha_com_violacao()

    assert _contrafactual(execucao, linha) == 0

    assert _publicado(execucao).resultado.solucoes


def test_entrada_real_linha_inconclusiva_nao_gera_correcao(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    execucao = validar_entrada_pela_cli(tmp_path)
    inconclusivas = execucao.linhas_so_inconclusivas()
    assert len(inconclusivas) == 2
    antes = instantaneo(tmp_path, sem=execucao.contrafactuais)
    for linha in inconclusivas:
        capsys.readouterr()
        assert _contrafactual(execucao, linha) == 2
        assert "counterfactual_recusado erro=contrafactual_sem_violacao" in capsys.readouterr().err
    assert not execucao.contrafactuais.exists()
    assert instantaneo(tmp_path, sem=execucao.contrafactuais) == antes


def test_ingest_real_violacao_usa_o_contexto_gravado_pelo_validate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execucao = validar_ingest_pela_cli(tmp_path, "processamento")
    linha = execucao.linha_com_violacao()
    alvos = execucao.regras_em(linha, "VIOLACAO")
    inconclusivas = execucao.regras_em(linha, "INCONCLUSIVO")
    assert alvos == {_ESTAB_CBO}
    assert inconclusivas
    antes = instantaneo(tmp_path, sem=execucao.contrafactuais)
    chamadas = espiar_motor(monkeypatch)

    assert _contrafactual(execucao, linha) == 0

    publicado = _publicado(execucao)
    resultado = publicado.resultado
    assert set(resultado.regras_alvo) == alvos
    assert inconclusivas.isdisjoint(resultado.regras_alvo)
    assert [c.sobreposta for c in chamadas] == [False]
    assert chamadas[0].estados[(linha, _ESTAB_CBO)] == "VIOLACAO"
    assert resultado.solucoes == ()
    assert resultado.candidatos_avaliados == 0
    assert resultado.motivo_parada is MotivoParada.SEM_OPERACAO_ADMISSIVEL
    assert resultado.minimalidade is Minimalidade.BUSCA_INCONCLUSIVA
    assert resultado.aprovacao_garantida is False
    assert publicado.bruto["aprovacao_garantida"] is False
    assert instantaneo(tmp_path, sem=execucao.contrafactuais) == antes


def test_ingest_real_linha_inconclusiva_nao_gera_correcao(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    execucao = validar_ingest_pela_cli(tmp_path, "documented")
    inconclusivas = execucao.linhas_so_inconclusivas()
    assert inconclusivas
    antes = instantaneo(tmp_path, sem=execucao.contrafactuais)
    for linha in inconclusivas:
        capsys.readouterr()
        assert _contrafactual(execucao, linha) == 2
        assert "counterfactual_recusado erro=contrafactual_sem_violacao" in capsys.readouterr().err
    assert not execucao.contrafactuais.exists()
    assert instantaneo(tmp_path, sem=execucao.contrafactuais) == antes
