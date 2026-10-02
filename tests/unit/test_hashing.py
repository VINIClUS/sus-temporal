import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
from hypothesis import given
from hypothesis import strategies as st

from sustemporal.contracts.config import RuntimeConfig
from sustemporal.duck import conectar
from sustemporal.hashing import hash_logico_linhas, hash_logico_relacao, sha256_arquivo

COLUNAS = ("texto", "inteiro", "valor", "data", "ativo")
CRIAR_T = (
    "CREATE TABLE t (texto VARCHAR, inteiro BIGINT, valor DECIMAL(18,2), data DATE, ativo BOOLEAN)"
)
INSERIR_T = "INSERT INTO t VALUES (?, ?, ?, ?, ?)"
LIMITE_DECIMAL = Decimal("9999999999999999.99")
CASOS_NULO = [None, "\x00N", "N"]
TABELA_GRANDE = """
CREATE TABLE t AS
SELECT
    CASE WHEN i % 7 = 0 THEN NULL ELSE 'v' || CAST(i % 1000 AS VARCHAR) || 'é|:' END AS texto,
    CASE WHEN i % 11 = 0 THEN NULL ELSE CAST(i % 5000 - 2500 AS BIGINT) END AS inteiro,
    CASE WHEN i % 13 = 0 THEN NULL ELSE CAST((i % 100000) * 0.01 AS DECIMAL(18,2)) END AS valor,
    CASE WHEN i % 17 = 0 THEN NULL ELSE DATE '2018-01-01' + CAST(i % 2922 AS INTEGER) END AS data,
    CASE WHEN i % 19 = 0 THEN NULL ELSE i % 2 = 0 END AS ativo
FROM range(300000) AS r(i)
"""

_texto = st.text(st.characters(codec="utf-8") | st.sampled_from("|:é日\x00"), max_size=8)
_linha = st.tuples(
    st.none() | _texto,
    st.none() | st.integers(min_value=-(2**63), max_value=2**63 - 1),
    st.none()
    | st.decimals(
        min_value=-LIMITE_DECIMAL,
        max_value=LIMITE_DECIMAL,
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
    st.none() | st.dates(),
    st.none() | st.booleans(),
)
_linhas = st.lists(_linha, max_size=25)


def _conexao(threads: int = 2) -> duckdb.DuckDBPyConnection:
    return conectar(RuntimeConfig(duckdb_memoria="512MB", duckdb_threads=threads))


def _carregar(con: duckdb.DuckDBPyConnection, linhas: Sequence[Sequence[object]]) -> None:
    con.execute(CRIAR_T)
    if linhas:
        con.executemany(INSERIR_T, [list(linha) for linha in linhas])


def _campo_esperado(texto: str | None) -> str:
    return "N" if texto is None else f"{len(texto.encode('utf-8'))}:{texto}"


def _hash_esperado(colunas: Sequence[str], textos: Sequence[Sequence[str | None]]) -> str:
    codificadas = ("|".join(_campo_esperado(texto) for texto in linha) for linha in textos)
    digests = sorted(hashlib.sha256(c.encode("utf-8")).hexdigest() for c in codificadas)
    corpo = "lh1\n" + "|".join(colunas) + "\n" + "".join(f"{d}\n" for d in digests)
    return "lh1:" + hashlib.sha256(corpo.encode("utf-8")).hexdigest()


def test_hash_segue_codificacao_canonica_documentada() -> None:
    colunas = ["texto", "inteiro", "valor", "data", "ativo", "instante"]
    meio_dia_utc = datetime(2024, 1, 1, 12, tzinfo=UTC)
    nove_horas_brt = datetime(2024, 1, 1, 9, tzinfo=timezone(timedelta(hours=-3)))
    linhas = [
        ("é|:日", 7, Decimal("1.20"), date(2024, 2, 29), True, meio_dia_utc),
        (None, -1, Decimal("0.00"), None, False, None),
        ("", 0, Decimal("-10.50"), date(1, 1, 1), None, nove_horas_brt),
    ]
    textos = [
        ["é|:日", "7", "1.2", "2024-02-29", "true", "2024-01-01T12:00:00+00:00"],
        [None, "-1", "0", None, "false", None],
        ["", "0", "-10.5", "0001-01-01", None, "2024-01-01T12:00:00+00:00"],
    ]
    assert hash_logico_linhas(colunas, linhas) == _hash_esperado(colunas, textos)


def test_duckdb_segue_codificacao_canonica_documentada() -> None:
    linhas = [
        ("é|:日", 7, Decimal("1.20"), date(2024, 2, 29), True),
        (None, None, None, None, None),
        ("", -1, Decimal("100.00"), date(1, 1, 1), False),
    ]
    textos = [
        ["é|:日", "7", "1.2", "2024-02-29", "true"],
        [None] * 5,
        ["", "-1", "100", "0001-01-01", "false"],
    ]
    with _conexao() as con:
        _carregar(con, linhas)
        assert hash_logico_relacao(con, "t", COLUNAS) == _hash_esperado(COLUNAS, textos)


def test_nulo_nao_colide_com_textos_parecidos() -> None:
    hashes = {hash_logico_linhas(["texto"], [[valor]]) for valor in CASOS_NULO}
    assert len(hashes) == len(CASOS_NULO)
    assert hash_logico_linhas(["texto"], [[None]]) == _hash_esperado(["texto"], [[None]])


@pytest.mark.parametrize("valor", CASOS_NULO)
def test_duckdb_coincide_com_referencia_para_nulo_e_textos_parecidos(valor: str | None) -> None:
    with _conexao() as con:
        con.execute("CREATE TABLE t (texto VARCHAR)")
        con.execute("INSERT INTO t VALUES (?)", [valor])
        assert hash_logico_relacao(con, "t", ["texto"]) == hash_logico_linhas(["texto"], [[valor]])


@given(_linhas)
def test_resultado_tem_formato_lh1(linhas: list[tuple[object, ...]]) -> None:
    assert re.fullmatch(r"lh1:[0-9a-f]{64}", hash_logico_linhas(COLUNAS, linhas))


@given(st.data())
def test_hash_nao_depende_da_ordem_das_linhas(data: st.DataObject) -> None:
    linhas = data.draw(_linhas)
    embaralhadas = data.draw(st.permutations(linhas))
    assert hash_logico_linhas(COLUNAS, embaralhadas) == hash_logico_linhas(COLUNAS, linhas)


@given(st.data())
def test_duplicar_linha_altera_hash(data: st.DataObject) -> None:
    linhas = data.draw(st.lists(_linha, min_size=1, max_size=25))
    indice = data.draw(st.integers(min_value=0, max_value=len(linhas) - 1))
    duplicada = [*linhas, linhas[indice]]
    assert hash_logico_linhas(COLUNAS, duplicada) != hash_logico_linhas(COLUNAS, linhas)


@given(st.data())
def test_remover_linha_altera_hash(data: st.DataObject) -> None:
    linhas = data.draw(st.lists(_linha, min_size=1, max_size=25))
    indice = data.draw(st.integers(min_value=0, max_value=len(linhas) - 1))
    restantes = linhas[:indice] + linhas[indice + 1 :]
    assert hash_logico_linhas(COLUNAS, restantes) != hash_logico_linhas(COLUNAS, linhas)


@given(st.data())
def test_duckdb_coincide_com_referencia_em_linhas_aleatorias(data: st.DataObject) -> None:
    linhas = data.draw(_linhas)
    ordem = data.draw(st.permutations(range(len(COLUNAS))))
    colunas = [COLUNAS[i] for i in ordem]
    reordenadas = [[linha[i] for i in ordem] for linha in linhas]
    with _conexao() as con:
        _carregar(con, linhas)
        assert hash_logico_relacao(con, "t", colunas) == hash_logico_linhas(colunas, reordenadas)


def test_duckdb_preserva_multiplicidade() -> None:
    linha = ("x", 1, Decimal("1.00"), date(2024, 1, 1), True)
    with _conexao() as con:
        _carregar(con, [linha])
        uma = hash_logico_relacao(con, "t", COLUNAS)
        con.execute(INSERIR_T, list(linha))
        duas = hash_logico_relacao(con, "t", COLUNAS)
    assert duas != uma
    assert duas == hash_logico_linhas(COLUNAS, [linha, linha])


def test_colunas_homonimas_do_alias_e_do_parametro_nao_interferem() -> None:
    colunas = ["digest", "campo_nulo"]
    linhas = [("z", None), ("a", "x"), ("m", "y"), (None, "q")]
    with _conexao() as con:
        con.execute("CREATE TABLE t (digest VARCHAR, campo_nulo VARCHAR)")
        con.executemany("INSERT INTO t VALUES (?, ?)", [list(linha) for linha in linhas])
        assert hash_logico_relacao(con, "t", colunas) == hash_logico_linhas(colunas, linhas)


def test_nomes_e_ordem_das_colunas_fazem_parte_do_hash() -> None:
    base = hash_logico_linhas(["a", "b"], [["x", "y"]])
    assert hash_logico_linhas(["a", "c"], [["x", "y"]]) != base
    assert hash_logico_linhas(["b", "a"], [["y", "x"]]) != base


def test_decimal_com_zeros_a_direita_tem_mesmo_hash() -> None:
    com_zero = hash_logico_linhas(["valor"], [[Decimal("1.20")]])
    assert com_zero == hash_logico_linhas(["valor"], [[Decimal("1.2")]])


@pytest.mark.parametrize("zero", ["0.00", "-0", "-0.000", "0E+3"])
def test_todo_zero_decimal_tem_o_mesmo_hash(zero: str) -> None:
    assert hash_logico_linhas(["valor"], [[Decimal(zero)]]) == hash_logico_linhas(
        ["valor"], [[Decimal(0)]]
    )


def test_duckdb_normaliza_decimais_de_escalas_diferentes() -> None:
    valores = [[Decimal(texto)] for texto in ("1.2", "0", "-0.5", "100", "10.01")]
    esperado = hash_logico_linhas(["valor"], valores)
    with _conexao() as con:
        con.execute("CREATE TABLE a (valor DECIMAL(18,2))")
        con.execute("CREATE TABLE b (valor DECIMAL(12,4))")
        con.executemany("INSERT INTO a VALUES (?)", valores)
        con.executemany("INSERT INTO b VALUES (?)", valores)
        assert hash_logico_relacao(con, "a", ["valor"]) == esperado
        assert hash_logico_relacao(con, "b", ["valor"]) == esperado


def test_duckdb_preserva_zeros_de_decimal_sem_casas() -> None:
    with _conexao() as con:
        con.execute("CREATE TABLE t (valor DECIMAL(9,0))")
        con.executemany("INSERT INTO t VALUES (?)", [[Decimal("100")], [Decimal("0")], [-70]])
        hash_duckdb = hash_logico_relacao(con, "t", ["valor"])
    assert hash_duckdb == _hash_esperado(["valor"], [["100"], ["0"], ["-70"]])


def test_decimal_de_38_digitos_nao_e_arredondado() -> None:
    valor = Decimal("12345678901234567890123456789.123456789")
    vizinho = Decimal("12345678901234567890123456789.123456788")
    esperado = _hash_esperado(["valor"], [[str(valor)]])
    assert hash_logico_linhas(["valor"], [[valor]]) == esperado
    assert hash_logico_linhas(["valor"], [[vizinho]]) != esperado
    with _conexao() as con:
        con.execute("CREATE TABLE t (valor DECIMAL(38,9))")
        con.execute("INSERT INTO t VALUES (?)", [valor])
        assert hash_logico_relacao(con, "t", ["valor"]) == esperado


def test_duckdb_converte_todos_os_inteiros_em_digitos() -> None:
    extremos = ["-128", "-2147483648", "170141183460469231731687303715884105727"]
    textos = [*extremos, "18446744073709551615"]
    colunas = ["a", "b", "c", "d"]
    with _conexao() as con:
        con.execute("CREATE TABLE t (a TINYINT, b INTEGER, c HUGEINT, d UBIGINT)")
        con.execute("INSERT INTO t VALUES (?, ?, ?, ?)", textos)
        assert hash_logico_relacao(con, "t", colunas) == _hash_esperado(colunas, [textos])


def test_float_e_proibido_no_hash_logico() -> None:
    with pytest.raises(TypeError, match="float_proibido_no_hash_logico"):
        hash_logico_linhas(["valor"], [[1.5]])


@pytest.mark.parametrize("ddl", ["CREATE TABLE t (valor DOUBLE)", "CREATE TABLE t (valor FLOAT)"])
def test_coluna_flutuante_e_proibida_no_duckdb(ddl: str) -> None:
    with _conexao() as con:
        con.execute(ddl)
        with pytest.raises(TypeError, match="float_proibido_no_hash_logico"):
            hash_logico_relacao(con, "t", ["valor"])


def test_coluna_de_tipo_nao_suportado_e_recusada_no_duckdb() -> None:
    with _conexao() as con:
        con.execute("CREATE TABLE t (instante TIMESTAMP)")
        with pytest.raises(TypeError, match="tipo_nao_suportado_no_hash_logico"):
            hash_logico_relacao(con, "t", ["instante"])


def test_tipo_python_nao_suportado_e_recusado() -> None:
    with pytest.raises(TypeError, match="tipo_nao_suportado_no_hash_logico tipo=bytes"):
        hash_logico_linhas(["valor"], [[b"x"]])


@pytest.mark.parametrize("valor", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_decimal_nao_finito_e_recusado(valor: str) -> None:
    with pytest.raises(ValueError, match="decimal_nao_finito"):
        hash_logico_linhas(["valor"], [[Decimal(valor)]])


def test_instante_sem_fuso_e_recusado() -> None:
    ingenuo = datetime(2024, 1, 1, 12)  # noqa: DTZ001
    with pytest.raises(ValueError, match="instante_sem_fuso"):
        hash_logico_linhas(["instante"], [[ingenuo]])


def test_linha_com_aridade_divergente_e_recusada() -> None:
    with pytest.raises(ValueError, match="linha_com_aridade_divergente esperado=2 obtido=1"):
        hash_logico_linhas(["a", "b"], [["x"]])


def test_referencia_recusa_lista_de_colunas_vazia() -> None:
    with pytest.raises(ValueError, match="hash_logico_sem_colunas"):
        hash_logico_linhas([], [[]])


def test_duckdb_recusa_lista_de_colunas_vazia() -> None:
    with _conexao() as con:
        _carregar(con, [])
        with pytest.raises(ValueError, match="hash_logico_sem_colunas"):
            hash_logico_relacao(con, "t", [])


def test_referencia_recusa_nome_de_coluna_ambiguo() -> None:
    with pytest.raises(ValueError, match="identificador_nao_permitido"):
        hash_logico_linhas(["a|b"], [["x"]])


@pytest.mark.parametrize("tabela", ["inexistente", 't"; DROP TABLE t; --', "T", "main.t"])
def test_rejeita_tabela_fora_do_catalogo_ou_maliciosa(tabela: str) -> None:
    with _conexao() as con:
        _carregar(con, [("x", 1, None, None, None)])
        with pytest.raises(ValueError, match="identificador_nao_permitido"):
            hash_logico_relacao(con, tabela, COLUNAS)
        assert con.execute("SELECT count(*) FROM t").fetchone() == (1,)


@pytest.mark.parametrize("coluna", ["inexistente", 'texto"; DROP TABLE t; --', "TEXTO"])
def test_rejeita_coluna_fora_da_tabela(coluna: str) -> None:
    with _conexao() as con:
        _carregar(con, [])
        with pytest.raises(ValueError, match="identificador_nao_permitido"):
            hash_logico_relacao(con, "t", ["texto", coluna])


def _hash_tabela_grande(threads: int) -> str:
    with _conexao(threads) as con:
        con.execute(TABELA_GRANDE)
        return hash_logico_relacao(con, "t", COLUNAS)


def test_hash_independe_do_numero_de_threads() -> None:
    assert _hash_tabela_grande(1) == _hash_tabela_grande(4)


def test_ida_e_volta_por_parquet_preserva_hash(tmp_path: Path) -> None:
    linhas = [
        ("é|:日", 7, Decimal("1.20"), date(2024, 2, 29), True),
        ("é|:日", 7, Decimal("1.20"), date(2024, 2, 29), True),
        (None, None, None, None, None),
        ("", -(2**63), -LIMITE_DECIMAL, date(1, 1, 1), False),
        ("a\x00N", 2**63 - 1, Decimal("0.01"), date(9999, 12, 31), None),
    ]
    snappy, zstd = tmp_path / "snappy.parquet", tmp_path / "zstd.parquet"
    with _conexao() as con:
        _carregar(con, linhas)
        original = hash_logico_relacao(con, "t", COLUNAS)
        con.execute(
            "COPY (SELECT * FROM t ORDER BY inteiro) TO ? (FORMAT parquet, COMPRESSION snappy)",
            [str(snappy)],
        )
        con.execute(
            "COPY (SELECT * FROM t ORDER BY inteiro DESC) TO ? "
            "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 2)",
            [str(zstd)],
        )
        con.execute("CREATE TABLE lido AS SELECT * FROM read_parquet(?)", [str(snappy)])
        con.read_parquet(str(zstd)).create_view("visao_parquet")
        assert hash_logico_relacao(con, "lido", COLUNAS) == original
        assert hash_logico_relacao(con, "visao_parquet", COLUNAS) == original
    assert sha256_arquivo(snappy) != sha256_arquivo(zstd)
    assert original == hash_logico_linhas(COLUNAS, linhas)


def test_sha256_arquivo_coincide_com_hashlib_em_varios_blocos(tmp_path: Path) -> None:
    conteudo = bytes(range(256)) * 10_241
    caminho = tmp_path / "grande.bin"
    caminho.write_bytes(conteudo)
    assert len(conteudo) > 2 * 1024 * 1024
    assert sha256_arquivo(caminho) == hashlib.sha256(conteudo).hexdigest()


def test_sha256_arquivo_vazio(tmp_path: Path) -> None:
    caminho = tmp_path / "vazio.bin"
    caminho.write_bytes(b"")
    assert sha256_arquivo(caminho) == hashlib.sha256(b"").hexdigest()


def test_mesmo_instante_em_fusos_distintos_tem_o_mesmo_hash() -> None:
    utc = datetime(2024, 1, 1, 12, tzinfo=UTC)
    brt = datetime(2024, 1, 1, 9, tzinfo=timezone(timedelta(hours=-3)))
    assert hash_logico_linhas(["instante"], [(utc,)]) == hash_logico_linhas(["instante"], [(brt,)])
