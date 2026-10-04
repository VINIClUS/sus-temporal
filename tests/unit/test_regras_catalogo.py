"""Catálogo formal de regras, independência da referência e comando `validate`."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.rules import EstadoRegra
from sustemporal.rules import reference
from sustemporal.rules.catalog import (
    CATALOGO_REGRAS,
    CatalogoInvalido,
    carregar_regras,
    catalogo_sha256,
    requisito_auxiliar,
    sql_da_familia,
    sql_de_avaliacao,
)

_FAMILIAS = {
    "PROCEDIMENTO_CBO",
    "ESTABELECIMENTO_CBO",
    "INSTRUMENTO_REGISTRO",
    "VIGENCIA_PROCEDIMENTO",
}


def test_catalogo_tem_as_quatro_familias_do_primeiro_incremento_como_candidatas() -> None:
    regras = carregar_regras()
    assert {regra.familia.value for regra in regras} == _FAMILIAS
    for regra in regras:
        assert regra.estado is EstadoRegra.CANDIDATA_PRE_G0
        assert regra.decisao_g0 is None
        assert regra.referencia.estado.value == "PENDENTE"
        assert regra.referencia.confirmacao.value == "A_CONFIRMAR"
        assert regra.pressupostos
        assert regra.criterios_temporais == ()
        assert requisito_auxiliar(regra).fonte is not FamiliaFonte.SIA_PA
        assert sql_da_familia(regra.familia)


def test_sql_e_parametrizado_e_so_tem_os_marcadores_de_allowlist() -> None:
    modelo = sql_de_avaliacao()
    assert modelo.count("{campo_faltando}") == 1
    assert modelo.count("{predicado}") == 1
    for regra in carregar_regras():
        texto = sql_da_familia(regra.familia)
        assert "{campo_faltando}" not in texto
        assert "{predicado}" not in texto
        assert "0301010072" not in texto


def _copiar_catalogo(destino: Path) -> Path:
    for origem in CATALOGO_REGRAS.rglob("*.yaml"):
        alvo = destino / origem.relative_to(CATALOGO_REGRAS)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(origem.read_text(encoding="utf-8"), encoding="utf-8")
    return destino


def test_catalogo_rejeita_campo_fora_do_esquema(tmp_path: Path) -> None:
    raiz = _copiar_catalogo(tmp_path / "rules")
    alvo = next(raiz.rglob("PROC_CBO_SIGTAP.yaml"))
    alvo.write_text(
        alvo.read_text(encoding="utf-8").replace(
            "campos_necessarios: [instrumento, procedimento, cbo]",
            "campos_necessarios: [instrumento, procedimento, cbo_inexistente]",
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogoInvalido, match="campo_fora_do_esquema"):
        carregar_regras(raiz)


def test_catalogo_rejeita_regra_repetida(tmp_path: Path) -> None:
    raiz = _copiar_catalogo(tmp_path / "rules")
    origem = next(raiz.rglob("PROC_CBO_SIGTAP.yaml"))
    (origem.parent / "COPIA.yaml").write_text(origem.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(CatalogoInvalido, match="repetidas"):
        carregar_regras(raiz)


def test_hash_do_catalogo_muda_com_a_regra() -> None:
    regras = carregar_regras()
    alterada = [regras[0].model_copy(update={"versao": "9.9.9"}), *regras[1:]]
    assert catalogo_sha256(regras) == catalogo_sha256(list(reversed(regras)))
    assert catalogo_sha256(alterada) != catalogo_sha256(regras)


_PROIBIDOS = ("sustemporal.rules.engine", "sustemporal.rules.sql", "sustemporal.temporal")


def test_referencia_nao_importa_o_motor_nem_o_seletor() -> None:
    modulos: set[str] = set()
    for arquivo in Path(reference.__file__).parent.glob("reference*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                modulos |= {alias.name for alias in no.names}
            elif isinstance(no, ast.ImportFrom) and no.module:
                modulos.add(no.module)
    internos = {m for m in modulos if m.startswith("sustemporal")}
    permitidos = ("sustemporal.contracts", "sustemporal.rules.reference")
    assert all(m.startswith(permitidos) for m in internos)
    assert "duckdb" not in modulos
    codigo = (
        "import sys, sustemporal.rules.reference; "
        f"print([m for m in sys.modules if m.startswith({_PROIBIDOS!r}) or m == 'duckdb'])"
    )
    saida = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, check=True
    )
    assert saida.stdout.strip() == "[]"
