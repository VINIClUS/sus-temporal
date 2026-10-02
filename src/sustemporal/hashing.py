"""Hash lógico `lh1` de uma tabela vista como multiconjunto de linhas."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, date, datetime
from decimal import MAX_EMAX, MAX_PREC, MIN_EMIN, Context, Decimal
from typing import TYPE_CHECKING, Any

from sustemporal.duck import identificador_seguro

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
    from pathlib import Path

    import duckdb

__all__ = ["hash_logico_linhas", "hash_logico_relacao", "sha256_arquivo"]

logger = logging.getLogger(__name__)

_VERSAO = "lh1"
# Sem prefixo de comprimento: campo não nulo sempre começa por dígito, então "N" nunca colide.
_CAMPO_NULO = "N"
_BLOCO_ARQUIVO = 1024 * 1024
_LOTE_DIGESTS = 10_000
_CONTEXTO_EXATO = Context(prec=MAX_PREC, Emax=MAX_EMAX, Emin=MIN_EMIN)
_FLUTUANTES_SQL = frozenset({"FLOAT", "DOUBLE"})
_INTEIROS_SQL = frozenset(
    {
        "TINYINT",
        "SMALLINT",
        "INTEGER",
        "BIGINT",
        "HUGEINT",
        "UTINYINT",
        "USMALLINT",
        "UINTEGER",
        "UBIGINT",
        "UHUGEINT",
    }
)
_TEXTO_SQL = {
    "VARCHAR": "{c}",
    "DATE": "CAST({c} AS VARCHAR)",
    "BOOLEAN": "CASE WHEN {c} THEN 'true' ELSE 'false' END",
    **dict.fromkeys(_INTEIROS_SQL, "CAST({c} AS VARCHAR)"),
}
_DECIMAL_SQL = re.compile(r"DECIMAL\((\d+),(\d+)\)")


def _texto_booleano(valor: bool) -> str:
    return "true" if valor else "false"


def _texto_decimal(valor: Decimal) -> str:
    if not valor.is_finite():
        raise ValueError(f"decimal_nao_finito valor={valor}")
    if valor.is_zero():
        return "0"
    return format(valor.normalize(_CONTEXTO_EXATO), "f")


def _texto_instante(valor: datetime) -> str:
    if valor.utcoffset() is None:
        raise ValueError(f"instante_sem_fuso valor={valor.isoformat()}")
    return valor.astimezone(UTC).isoformat()


_CONVERSORES: tuple[tuple[type[Any], Callable[[Any], str]], ...] = (
    (bool, _texto_booleano),
    (str, str),
    (int, str),
    (Decimal, _texto_decimal),
    (datetime, _texto_instante),
    (date, date.isoformat),
)


def _texto_canonico(valor: object) -> str:
    if isinstance(valor, float):
        raise TypeError("float_proibido_no_hash_logico")
    for tipo, converter in _CONVERSORES:
        if isinstance(valor, tipo):
            return converter(valor)
    raise TypeError(f"tipo_nao_suportado_no_hash_logico tipo={type(valor).__name__}")


def _campo(valor: object) -> str:
    if valor is None:
        return _CAMPO_NULO
    texto = _texto_canonico(valor)
    return f"{len(texto.encode('utf-8'))}:{texto}"


def _digest_linha(linha: Sequence[object], aridade: int) -> str:
    if len(linha) != aridade:
        raise ValueError(f"linha_com_aridade_divergente esperado={aridade} obtido={len(linha)}")
    codificada = "|".join(_campo(valor) for valor in linha)
    return hashlib.sha256(codificada.encode("utf-8")).hexdigest()


def _validar_colunas(colunas: Sequence[str], permitidas: Collection[str]) -> list[str]:
    if not colunas:
        raise ValueError("hash_logico_sem_colunas")
    return [identificador_seguro(nome, permitidas) for nome in colunas]


def _combinar(colunas: Sequence[str], trechos: Iterable[str]) -> str:
    acumulador = hashlib.sha256(f"{_VERSAO}\n{'|'.join(colunas)}\n".encode())
    for trecho in trechos:
        acumulador.update(trecho.encode("utf-8"))
    return f"{_VERSAO}:{acumulador.hexdigest()}"


def hash_logico_linhas(colunas: Sequence[str], linhas: Iterable[Sequence[object]]) -> str:
    """Referência em Python puro do hash lógico do multiconjunto de linhas.

    Raises:
        TypeError: valor float ou de tipo não suportado.
        ValueError: coluna inválida, aridade divergente, decimal não finito ou instante sem fuso.
    """
    _validar_colunas(colunas, colunas)
    digests = sorted(_digest_linha(linha, len(colunas)) for linha in linhas)
    return _combinar(colunas, (f"{digest}\n" for digest in digests))


def _texto_sql(coluna: str, tipo: str) -> str:
    if tipo in _FLUTUANTES_SQL:
        raise TypeError(f"float_proibido_no_hash_logico coluna={coluna} tipo={tipo}")
    modelo = _TEXTO_SQL.get(tipo)
    if modelo is not None:
        return modelo.format(c=coluna)
    decimal = _DECIMAL_SQL.fullmatch(tipo)
    if decimal is None:
        raise TypeError(f"tipo_nao_suportado_no_hash_logico coluna={coluna} tipo={tipo}")
    if decimal.group(2) == "0":
        return f"CAST({coluna} AS VARCHAR)"
    aparado = f"rtrim(rtrim(CAST({coluna} AS VARCHAR), '0'), '.')"
    return f"CASE WHEN {coluna} = 0 THEN '0' ELSE {aparado} END"


def _campo_sql(coluna: str, tipo: str) -> str:
    texto = _texto_sql(coluna, tipo)
    return (
        f"CASE WHEN {coluna} IS NULL THEN $campo_nulo "
        f"ELSE CAST(strlen({texto}) AS VARCHAR) || ':' || {texto} END"
    )


def _descrever(con: duckdb.DuckDBPyConnection, tabela: str) -> tuple[str, dict[str, str]]:
    catalogo = con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    tabela_sql = identificador_seguro(tabela, {str(linha[0]) for linha in catalogo})
    descricao = con.execute(f"DESCRIBE {tabela_sql}").fetchall()
    return tabela_sql, {str(linha[0]): str(linha[1]) for linha in descricao}


def _lotes_de_digests(con: duckdb.DuckDBPyConnection) -> Iterator[str]:
    while lote := con.fetchmany(_LOTE_DIGESTS):
        yield "".join(f"{linha[0]}\n" for linha in lote)


def hash_logico_relacao(con: duckdb.DuckDBPyConnection, tabela: str, colunas: Sequence[str]) -> str:
    """Hash lógico calculado no DuckDB; igual a `hash_logico_linhas` sobre os mesmos dados.

    Raises:
        TypeError: coluna FLOAT/DOUBLE ou de tipo não suportado.
        ValueError: tabela fora do catálogo, coluna fora da tabela ou nome fora do padrão.
    """
    tabela_sql, tipos = _descrever(con, tabela)
    citadas = _validar_colunas(colunas, tipos)
    campos = [
        _campo_sql(citada, tipos[nome]) for citada, nome in zip(citadas, colunas, strict=True)
    ]
    linha_sql = " || '|' || ".join(campos)
    con.execute(
        f"SELECT sha256({linha_sql}) AS digest FROM {tabela_sql} ORDER BY digest",  # noqa: S608
        {"campo_nulo": _campo(None)},
    )
    resultado = _combinar(colunas, _lotes_de_digests(con))
    logger.info(
        "hash_logico_calculado tabela=%s colunas=%d hash=%s", tabela, len(colunas), resultado
    )
    return resultado


def sha256_arquivo(caminho: Path) -> str:
    """SHA-256 hexadecimal do arquivo, lido em blocos de 1 MiB."""
    acumulador = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        while bloco := arquivo.read(_BLOCO_ARQUIVO):
            acumulador.update(bloco)
    return acumulador.hexdigest()
