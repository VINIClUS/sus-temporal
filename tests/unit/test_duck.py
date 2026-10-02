import re
from pathlib import Path

import duckdb
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.duck import conectar, identificador_seguro

PADRAO_IDENTIFICADOR = re.compile(r"[a-z_][a-z0-9_]*")


def _configuracao(con: duckdb.DuckDBPyConnection, nome: str) -> object:
    linha = con.execute("SELECT current_setting(?)", [nome]).fetchone()
    assert linha is not None
    return linha[0]


def test_conectar_aplica_threads_do_runtime() -> None:
    with conectar(RuntimeConfig(duckdb_threads=3)) as con:
        assert _configuracao(con, "threads") == 3


def test_conectar_aplica_limite_de_memoria_do_runtime() -> None:
    with conectar(RuntimeConfig(duckdb_memoria="256MB")) as con, duckdb.connect() as referencia:
        referencia.execute("SET memory_limit = '256MB'")
        assert _configuracao(con, "memory_limit") == _configuracao(referencia, "memory_limit")


def test_conectar_desliga_instalacao_e_carga_automatica_de_extensoes() -> None:
    with conectar(RuntimeConfig()) as con:
        assert _configuracao(con, "autoinstall_known_extensions") is False
        assert _configuracao(con, "autoload_known_extensions") is False


def test_conectar_usa_diretorio_temporario_informado(tmp_path: Path) -> None:
    with conectar(RuntimeConfig(), temporario=tmp_path) as con:
        assert _configuracao(con, "temp_directory") == str(tmp_path)


def test_conectar_abre_banco_em_arquivo(tmp_path: Path) -> None:
    banco = tmp_path / "catalogo.duckdb"
    with conectar(RuntimeConfig(), banco=str(banco)) as con:
        con.execute("CREATE TABLE t (a INTEGER)")
    assert banco.exists()


def test_identificador_permitido_sai_entre_aspas_duplas() -> None:
    assert identificador_seguro("valor_aprovado", {"valor_aprovado", "cnes"}) == '"valor_aprovado"'


def test_rejeita_identificador_fora_da_allowlist() -> None:
    with pytest.raises(ValueError, match="identificador_nao_permitido nome='senha'"):
        identificador_seguro("senha", {"cnes", "cbo"})


@pytest.mark.parametrize(
    "nome",
    [
        'x"; DROP TABLE t; --',
        "x' OR '1'='1",
        "cnes;",
        "a b",
        "esquema.tabela",
        "Maiuscula",
        "1coluna",
        "",
        "cnes\n",
        "ação",
        "a-b",
        "a/*c*/",
    ],
)
def test_rejeita_nome_com_cara_de_injecao_mesmo_na_allowlist(nome: str) -> None:
    with pytest.raises(ValueError, match="identificador_nao_permitido"):
        identificador_seguro(nome, {nome})


@given(st.from_regex(PADRAO_IDENTIFICADOR, fullmatch=True))
def test_aceita_qualquer_nome_do_padrao_presente_na_allowlist(nome: str) -> None:
    assert identificador_seguro(nome, [nome]) == f'"{nome}"'


@given(st.text(max_size=12).filter(lambda nome: PADRAO_IDENTIFICADOR.fullmatch(nome) is None))
def test_rejeita_qualquer_nome_fora_do_padrao(nome: str) -> None:
    with pytest.raises(ValueError, match="identificador_nao_permitido"):
        identificador_seguro(nome, [nome])
