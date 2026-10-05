"""CLI `sustemporal counterfactual` (T09) sobre uma execução SINTETICA; nada aqui é empírico."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from sustemporal.contracts.artifacts import EstadoIntegridade
from sustemporal.contracts.counterfactual import CounterfactualSearchResult, Executabilidade
from sustemporal.contracts.experiment import EstadoExecucao
from sustemporal.explanation import counterfactual_sobreposicao
from sustemporal.explanation.cli import localizar_execucao
from sustemporal.explanation.counterfactual import search_counterfactuals
from sustemporal.explanation.counterfactual_cli import (
    diretorio_contrafactual,
    executar_counterfactual,
    identidade_contrafactual,
)
from sustemporal.explanation.counterfactual_contexto import (
    ContextoIndisponivel,
    contexto_da_execucao,
)
from sustemporal.explanation.counterfactual_operacoes import (
    CATALOGO_OPERACOES,
    CatalogoOperacoesInvalido,
    carregar_operacoes,
)
from sustemporal.explanation.explain import montar_explicacao
from sustemporal.rules.cli import EntradaValidacao
from tests.fixtures.contrafactual_execucao import (
    ARQUIVO_ENTRADA,
    Execucao,
    executar_validacao_sintetica,
)

if TYPE_CHECKING:
    from sustemporal.contracts.experiment import RunResult

_INCLUIR = "INCLUIR_CBO_NO_ESTABELECIMENTO"


@pytest.fixture(scope="module")
def execucao(tmp_path_factory: pytest.TempPathFactory) -> Execucao:
    return executar_validacao_sintetica(tmp_path_factory.mktemp("cli_contrafactual"))


def _rodar(execucao: Execucao, row: str, run: str | None = None) -> int:
    args = argparse.Namespace(run=run or execucao.run_id, row=row)
    return executar_counterfactual(args, execucao.config)


def _saidas(execucao: Execucao) -> Path:
    return Path(execucao.config.runtime.raiz_saidas)


def _destino(execucao: Execucao, row: str) -> Path:
    identidade = identidade_contrafactual()
    return diretorio_contrafactual(_saidas(execucao), execucao.run_id, row, identidade)


def _resultado(execucao: Execucao, row: str) -> CounterfactualSearchResult:
    texto = (_destino(execucao, row) / "contrafactual.json").read_text(encoding="utf-8")
    return CounterfactualSearchResult.model_validate_json(texto)


def test_ausencia_pela_cli_publica_hipotese_sem_aprovacao(execucao: Execucao) -> None:
    assert _rodar(execucao, execucao.ausencia) == 0
    resultado = _resultado(execucao, execucao.ausencia)
    assert [[o.op_id for o in s.operacoes] for s in resultado.solucoes] == [[_INCLUIR]]
    assert resultado.solucoes[0].executabilidade is Executabilidade.HIPOTESE_PASSADA
    assert resultado.aprovacao_garantida is False
    bruto = json.loads((_destino(execucao, execucao.ausencia) / "contrafactual.json").read_text())
    assert bruto["aprovacao_garantida"] is False


def test_saida_e_imutavel_e_derivada_de_run_e_row(execucao: Execucao) -> None:
    assert _rodar(execucao, execucao.ausencia) == 0
    destino = _destino(execucao, execucao.ausencia)
    antes = {p.name: p.read_bytes() for p in destino.iterdir()}
    assert _rodar(execucao, execucao.ausencia) == 0
    assert {p.name: p.read_bytes() for p in destino.iterdir()} == antes
    assert destino.parent.parent == _saidas(execucao) / "contrafactuais" / execucao.run_id
    assert destino.parent.name == f"id_{identidade_contrafactual()}"
    identidade = json.loads((destino / "identidade.json").read_text(encoding="utf-8"))
    assert set(identidade) == {"catalogo_operacoes_sha256", "codigo", "identidade"}
    assert not list(destino.parent.glob(".*parcial*"))


@pytest.mark.parametrize("linha", ["mes_faltante", "borda_2018"])
def test_linha_sem_violacao_nao_gera_contrafactual_nem_usa_mes_vizinho(
    execucao: Execucao, linha: str
) -> None:
    row = getattr(execucao, linha)
    assert _rodar(execucao, row) == 2
    assert not _destino(execucao, row).exists()


def test_run_inexistente_da_saida_2(execucao: Execucao) -> None:
    assert _rodar(execucao, execucao.ausencia, run="val_inexistente") == 2


def test_row_inexistente_da_saida_2(execucao: Execucao) -> None:
    row = execucao.ausencia.replace("#0", "#99")
    assert _rodar(execucao, row) == 2
    assert not _destino(execucao, row).exists()


def test_argumento_invalido_da_saida_2(execucao: Execucao) -> None:
    assert _rodar(execucao, "nao_e_row_id") == 2


def _pasta_da_execucao(execucao: Execucao) -> Path:
    return _saidas(execucao) / "runs" / execucao.run_id


def test_entrada_da_execucao_ausente_da_saida_2(tmp_path: Path) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    (_pasta_da_execucao(execucao) / ARQUIVO_ENTRADA).unlink()
    assert _rodar(execucao, execucao.ausencia) == 2


def test_entrada_divergente_do_run_id_da_saida_2(tmp_path: Path) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    caminho = _pasta_da_execucao(execucao) / ARQUIVO_ENTRADA
    entrada = EntradaValidacao.model_validate_json(caminho.read_text(encoding="utf-8"))
    alterada = dict(entrada.integridade) | dict.fromkeys(
        entrada.integridade, EstadoIntegridade.NAO_VERIFICADO
    )
    caminho.write_text(
        entrada.model_copy(update={"integridade": alterada}).model_dump_json(), encoding="utf-8"
    )
    assert _rodar(execucao, execucao.ausencia) == 2
    assert not _destino(execucao, execucao.ausencia).exists()


def test_busca_de_dois_argumentos_resolve_pela_execucao(execucao: Execucao) -> None:
    run = localizar_execucao(_saidas(execucao), execucao.run_id)
    bundle = montar_explicacao(run, execucao.ausencia, runtime=execucao.config.runtime).bundle
    resultado = search_counterfactuals(bundle, execucao.config)
    assert [[o.op_id for o in s.operacoes] for s in resultado.solucoes] == [[_INCLUIR]]
    assert resultado.aprovacao_garantida is False


def test_execucao_sem_entrada_gravada_tem_contexto_ausente(tmp_path: Path) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    (_pasta_da_execucao(execucao) / ARQUIVO_ENTRADA).unlink()
    with pytest.raises(ContextoIndisponivel, match="contexto_da_execucao_ausente run="):
        contexto_da_execucao(_saidas(execucao), execucao.run_id, execucao.config)


def test_catalogo_de_operacoes_diferente_gera_outro_destino(
    execucao: Execucao, tmp_path: Path
) -> None:
    catalogo = tmp_path / "operations.yaml"
    texto = CATALOGO_OPERACOES.read_text(encoding="utf-8")
    catalogo.write_text(texto.replace('custo: "1"', 'custo: "2"', 1), encoding="utf-8")
    assert identidade_contrafactual(catalogo) != identidade_contrafactual()
    assert _rodar(execucao, execucao.ausencia) == 0
    original = (_destino(execucao, execucao.ausencia) / "contrafactual.json").read_bytes()
    args = argparse.Namespace(run=execucao.run_id, row=execucao.ausencia)
    assert executar_counterfactual(args, execucao.config, catalogo=catalogo) == 0
    outro = diretorio_contrafactual(
        _saidas(execucao), execucao.run_id, execucao.ausencia, identidade_contrafactual(catalogo)
    )
    assert outro != _destino(execucao, execucao.ausencia)
    resultado = CounterfactualSearchResult.model_validate_json(
        (outro / "contrafactual.json").read_text(encoding="utf-8")
    )
    assert resultado.solucoes[0].custo == 2
    assert (_destino(execucao, execucao.ausencia) / "contrafactual.json").read_bytes() == original


def test_falha_sem_gravacao_nao_deixa_resultado_antigo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    assert _rodar(execucao, execucao.ausencia) == 0
    destino = _destino(execucao, execucao.ausencia)
    assert (destino / "contrafactual.json").exists()
    real = counterfactual_sobreposicao.evaluate_rules

    def parcial(*args: Any, **kwargs: Any) -> RunResult:
        return real(*args, **kwargs).model_copy(update={"estado": EstadoExecucao.PARCIAL})

    escrever = Path.write_bytes

    def disco_cheio(caminho: Path, dados: bytes) -> int:
        if caminho.name == "falha.json":
            raise OSError("disco_cheio_sintetico")
        return escrever(caminho, dados)

    monkeypatch.setattr(counterfactual_sobreposicao, "evaluate_rules", parcial)
    monkeypatch.setattr(Path, "write_bytes", disco_cheio)
    assert _rodar(execucao, execucao.ausencia) == 5
    assert not destino.exists()


@pytest.mark.parametrize("conteudo", [b"\xff\xfe\x00nao_utf8", b'{"dataset": {"dataset_id"'])
def test_entrada_ilegivel_e_recusa_de_contexto(tmp_path: Path, conteudo: bytes) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    (_pasta_da_execucao(execucao) / ARQUIVO_ENTRADA).write_bytes(conteudo)
    with pytest.raises(ContextoIndisponivel, match="contrafactual_sem_contexto"):
        contexto_da_execucao(_saidas(execucao), execucao.run_id, execucao.config)
    assert _rodar(execucao, execucao.ausencia) == 2


@pytest.mark.parametrize(
    "conteudo", [b"\xff\xfe\x00nao_utf8", b'{"run_id": "val_\xe9"}'], ids=["binario", "latin1"]
)
def test_run_result_nao_utf8_e_recusa_de_execucao(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, conteudo: bytes
) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    (_pasta_da_execucao(execucao) / "run_result.json").write_bytes(conteudo)
    assert _rodar(execucao, execucao.ausencia) == 2
    assert "counterfactual_recusado erro=execucao_ilegivel" in caplog.text
    assert not _destino(execucao, execucao.ausencia).exists()
    with pytest.raises(
        ContextoIndisponivel, match=r"contrafactual_sem_contexto .*execucao_ilegivel"
    ):
        contexto_da_execucao(_saidas(execucao), execucao.run_id, execucao.config)


@pytest.mark.parametrize(
    "texto",
    [
        'versao: "1"\noperacoes: [\n',
        'versao: "1"\noperacoes:\n  - op_id: INCLUIR_CBO_NO_ESTABELECIMENTO\n    custo: "0"\n',
    ],
    ids=["yaml_malformado", "viola_contrato"],
)
def test_catalogo_de_operacoes_invalido_e_recusa_de_configuracao(
    execucao: Execucao, tmp_path: Path, texto: str
) -> None:
    catalogo = tmp_path / "operations.yaml"
    catalogo.write_text(texto, encoding="utf-8")
    args = argparse.Namespace(run=execucao.run_id, row=execucao.ausencia)
    assert executar_counterfactual(args, execucao.config, catalogo=catalogo) == 2
    with pytest.raises(CatalogoOperacoesInvalido, match="catalogo_operacoes_invalido"):
        carregar_operacoes(catalogo)


def test_catalogo_lido_uma_vez_define_identidade_e_busca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execucao = executar_validacao_sintetica(tmp_path / "execucao")
    catalogo = tmp_path / "operations.yaml"
    original = CATALOGO_OPERACOES.read_bytes()
    catalogo.write_bytes(original)
    alterado = original.replace(b'custo: "1"', b'custo: "2"', 1)
    abrir = Path.open
    lidas: list[Path] = []

    def alterar_depois_da_primeira_leitura(caminho: Path, *args: Any, **kwargs: Any) -> Any:
        arquivo = abrir(caminho, *args, **kwargs)
        if caminho != catalogo or lidas:
            return arquivo
        lidas.append(caminho)
        with arquivo:
            dados = arquivo.read()
        with open(catalogo, "wb") as destino:
            destino.write(alterado)
        return io.BytesIO(dados) if isinstance(dados, bytes) else io.StringIO(dados)

    monkeypatch.setattr(Path, "open", alterar_depois_da_primeira_leitura)
    args = argparse.Namespace(run=execucao.run_id, row=execucao.ausencia)
    assert executar_counterfactual(args, execucao.config, catalogo=catalogo) == 0
    monkeypatch.undo()
    identidade = _saidas(execucao) / "contrafactuais" / execucao.run_id
    (pasta,) = list(identidade.iterdir())
    (linha,) = list(pasta.iterdir())
    gravada = json.loads((linha / "identidade.json").read_text(encoding="utf-8"))
    assert gravada["catalogo_operacoes_sha256"] == hashlib.sha256(original).hexdigest()
    assert pasta.name == f"id_{gravada['identidade']}"
    resultado = CounterfactualSearchResult.model_validate_json(
        (linha / "contrafactual.json").read_text(encoding="utf-8")
    )
    assert resultado.solucoes[0].custo == 1


@pytest.mark.parametrize(
    ("instante", "esperado"),
    [
        (datetime(2020, 2, 29, 23, 59, 59, tzinfo=UTC), Executabilidade.INDETERMINADO),
        (datetime(2020, 3, 1, 0, 0, 0, tzinfo=UTC), Executabilidade.HIPOTESE_PASSADA),
    ],
)
def test_relogio_injetado_decide_a_executabilidade(
    tmp_path: Path, instante: datetime, esperado: Executabilidade
) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    args = argparse.Namespace(run=execucao.run_id, row=execucao.ausencia)
    assert executar_counterfactual(args, execucao.config, relogio=lambda: instante) == 0
    assert _resultado(execucao, execucao.ausencia).solucoes[0].executabilidade is esperado


_FIM_DE_FEVEREIRO = datetime(2020, 2, 29, 23, 59, 59, tzinfo=UTC)
_INICIO_DE_MARCO = datetime(2020, 3, 1, 0, 0, 0, tzinfo=UTC)
_FIM_DE_MARCO = datetime(2020, 3, 31, 23, 59, 59, tzinfo=UTC)


def _arquivos(pasta: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(pasta)): p.read_bytes() for p in sorted(pasta.rglob("*")) if p.is_file()
    }


def test_competencia_as_of_diferente_publica_outro_resultado_e_preserva_o_anterior(
    tmp_path: Path,
) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    args = argparse.Namespace(run=execucao.run_id, row=execucao.ausencia)
    raiz = _saidas(execucao) / "contrafactuais" / execucao.run_id
    assert executar_counterfactual(args, execucao.config, relogio=lambda: _FIM_DE_FEVEREIRO) == 0
    (fevereiro,) = list(raiz.iterdir())
    antes = _arquivos(fevereiro)
    assert executar_counterfactual(args, execucao.config, relogio=lambda: _INICIO_DE_MARCO) == 0
    pastas = sorted(raiz.iterdir())
    assert len(pastas) == 2
    assert _arquivos(fevereiro) == antes
    (marco,) = [pasta for pasta in pastas if pasta != fevereiro]
    meses = [
        json.loads(next(pasta.rglob("identidade.json")).read_text(encoding="utf-8"))
        for pasta in (fevereiro, marco)
    ]
    assert [identidade["competencia_as_of"] for identidade in meses] == ["202002", "202003"]


def test_instantes_do_mesmo_mes_as_of_mantem_a_identidade(tmp_path: Path) -> None:
    execucao = executar_validacao_sintetica(tmp_path)
    args = argparse.Namespace(run=execucao.run_id, row=execucao.ausencia)
    raiz = _saidas(execucao) / "contrafactuais" / execucao.run_id
    assert executar_counterfactual(args, execucao.config, relogio=lambda: _INICIO_DE_MARCO) == 0
    assert executar_counterfactual(args, execucao.config, relogio=lambda: _FIM_DE_MARCO) == 0
    assert len(list(raiz.iterdir())) == 1
