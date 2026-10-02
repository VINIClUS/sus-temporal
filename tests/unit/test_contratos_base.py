import hashlib
import json
import string
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import TypeAdapter, ValidationError

import sustemporal.contracts as contratos
from sustemporal.contracts.base import (
    Booleano,
    CodigoCBO,
    CodigoCNES,
    CodigoMunicipio6,
    CodigoMunicipio7,
    CodigoProcedimento,
    CodigoUF,
    Confirmacao,
    ContratoBase,
    Data,
    DocRef,
    EstadoDocumento,
    Falso,
    FileRef,
    InstanteUTC,
    Inteiro,
    InteiroNaoNegativo,
    MotivoAusencia,
    ValorMonetario,
    ValorNormalizado,
    Verdadeiro,
    hash_canonico,
    json_canonico,
)

_CODIGOS_NUMERICOS = {
    "cnes": (TypeAdapter(CodigoCNES), 7),
    "procedimento": (TypeAdapter(CodigoProcedimento), 10),
    "municipio6": (TypeAdapter(CodigoMunicipio6), 6),
    "municipio7": (TypeAdapter(CodigoMunicipio7), 7),
    "uf": (TypeAdapter(CodigoUF), 2),
}
_CBO = TypeAdapter(CodigoCBO)
_MONETARIO = TypeAdapter(ValorMonetario)
_INTEIRO = TypeAdapter(Inteiro)
_NAO_NEGATIVO = TypeAdapter(InteiroNaoNegativo)
_BOOLEANO = TypeAdapter(Booleano)
_VERDADEIRO = TypeAdapter(Verdadeiro)
_FALSO = TypeAdapter(Falso)
_INSTANTE = TypeAdapter(InstanteUTC)
_DATA = TypeAdapter(Data)
_ESCALARES_JSON = st.none() | st.booleans() | st.integers() | st.text(max_size=5)
_JSON = st.recursive(
    _ESCALARES_JSON,
    lambda filhos: st.lists(filhos, max_size=3) | st.dictionaries(st.text(max_size=5), filhos),
    max_leaves=12,
)


def _docref(**campos: object) -> DocRef:
    base: dict[str, object] = {
        "doc_id": "manual_sia",
        "titulo": "Manual técnico",
        "estado": "PENDENTE",
        "proveniencia": "SECUNDARIA",
    }
    return DocRef.model_validate(base | campos)


def _contratos() -> list[type[ContratoBase]]:
    classes = (
        objeto
        for objeto in vars(contratos).values()
        if isinstance(objeto, type) and issubclass(objeto, ContratoBase)
    )
    return sorted((c for c in classes if c is not ContratoBase), key=lambda c: c.__name__)


def _inverter_chaves(conteudo: object) -> object:
    if isinstance(conteudo, dict):
        return {chave: _inverter_chaves(conteudo[chave]) for chave in reversed(list(conteudo))}
    if isinstance(conteudo, list):
        return [_inverter_chaves(item) for item in conteudo]
    return conteudo


@given(nome=st.sampled_from(sorted(_CODIGOS_NUMERICOS)), dados=st.data())
def test_codigos_preservam_zeros_a_esquerda(nome: str, dados: st.DataObject) -> None:
    adaptador, tamanho = _CODIGOS_NUMERICOS[nome]
    resto = dados.draw(st.text(alphabet=string.digits, min_size=tamanho - 1, max_size=tamanho - 1))
    codigo = f"0{resto}"
    assert adaptador.validate_python(codigo) == codigo
    assert adaptador.validate_json(json.dumps(codigo)) == codigo


@pytest.mark.parametrize("nome", sorted(_CODIGOS_NUMERICOS))
@pytest.mark.parametrize("conversor", [int, float])
def test_codigos_rejeitam_inteiro_e_float(nome: str, conversor: type) -> None:
    adaptador, tamanho = _CODIGOS_NUMERICOS[nome]
    with pytest.raises(ValidationError):
        adaptador.validate_python(conversor("1" * tamanho))


@pytest.mark.parametrize("nome", sorted(_CODIGOS_NUMERICOS))
def test_codigos_rejeitam_comprimento_errado_ou_caractere_nao_digito(nome: str) -> None:
    adaptador, tamanho = _CODIGOS_NUMERICOS[nome]
    invalidos = ("1" * (tamanho - 1), "1" * (tamanho + 1), " " + "1" * (tamanho - 1))
    for texto in (*invalidos, "A" + "1" * (tamanho - 1), "1" * tamanho + "\n"):
        with pytest.raises(ValidationError):
            adaptador.validate_python(texto)


@pytest.mark.parametrize("nome", sorted(_CODIGOS_NUMERICOS))
def test_codigos_rejeitam_digitos_nao_ascii(nome: str) -> None:
    adaptador, tamanho = _CODIGOS_NUMERICOS[nome]
    with pytest.raises(ValidationError):
        adaptador.validate_python("١" * tamanho)


@given(st.text(alphabet=string.digits + string.ascii_uppercase, min_size=6, max_size=6))
def test_aceita_cbo_alfanumerico_maiusculo(cbo: str) -> None:
    assert _CBO.validate_python(cbo) == cbo


@given(letra=st.sampled_from(string.ascii_lowercase), posicao=st.integers(0, 5))
def test_rejeita_cbo_com_minuscula(letra: str, posicao: int) -> None:
    cbo = "2231F9"[:posicao] + letra + "2231F9"[posicao + 1 :]
    with pytest.raises(ValidationError):
        _CBO.validate_python(cbo)


@pytest.mark.parametrize("cbo", ["22512", "2251255", "2251 5", " 225125", "225-12", "", 225125])
def test_rejeita_cbo_com_espaco_tamanho_errado_ou_numero(cbo: object) -> None:
    with pytest.raises(ValidationError):
        _CBO.validate_python(cbo)


@pytest.mark.parametrize("valor", [1.5, 0.1, 10.0, True])
def test_valor_monetario_rejeita_float_e_bool(valor: object) -> None:
    with pytest.raises(ValidationError):
        _MONETARIO.validate_python(valor)


def test_valor_monetario_rejeita_float_vindo_de_json() -> None:
    with pytest.raises(ValidationError):
        _MONETARIO.validate_json("1.5")


@pytest.mark.parametrize(
    "valor",
    ["1.005", "0.001", "1.000", Decimal("2.345"), "1e2", "NaN", Decimal("NaN"), "1,50", " 1.50"],
)
def test_valor_monetario_rejeita_mais_de_duas_casas_ou_formato_invalido(valor: object) -> None:
    with pytest.raises(ValidationError):
        _MONETARIO.validate_python(valor)


@given(st.decimals(places=2, allow_nan=False, allow_infinity=False))
def test_valor_monetario_aceita_ate_duas_casas_sem_perder_exatidao(valor: Decimal) -> None:
    assert str(_MONETARIO.validate_python(str(valor))) == str(valor)
    assert _MONETARIO.validate_python(valor) == valor


def test_valor_monetario_e_decimal_e_soma_sem_erro_binario() -> None:
    soma = _MONETARIO.validate_python("0.10") + _MONETARIO.validate_python("0.20")
    assert isinstance(soma, Decimal)
    assert soma == Decimal("0.30")
    assert _MONETARIO.validate_python(7) == Decimal(7)


@given(st.integers(-(10**18), 10**18))
def test_inteiro_aceita_texto_de_digitos(numero: int) -> None:
    assert _INTEIRO.validate_python(str(numero)) == numero
    assert _INTEIRO.validate_python(numero) == numero


def test_inteiro_aceita_zeros_a_esquerda_em_texto() -> None:
    assert _INTEIRO.validate_python("0012") == 12


@pytest.mark.parametrize("valor", [True, False, 1.0, 2.5, "1.0", "1e3", " 1", "", "um", "+1"])
def test_inteiro_rejeita_bool_float_e_texto_nao_numerico(valor: object) -> None:
    with pytest.raises(ValidationError):
        _INTEIRO.validate_python(valor)


@pytest.mark.parametrize("valor", [-1, "-1"])
def test_inteiro_nao_negativo_rejeita_negativo(valor: object) -> None:
    with pytest.raises(ValidationError):
        _NAO_NEGATIVO.validate_python(valor)


@pytest.mark.parametrize(
    ("entrada", "esperado"), [(True, True), (False, False), ("true", True), ("false", False)]
)
def test_booleano_aceita_apenas_true_e_false(entrada: object, esperado: bool) -> None:
    assert _BOOLEANO.validate_python(entrada) is esperado


@pytest.mark.parametrize(
    "entrada", ["True", "FALSE", "1", "0", 1, 0, "yes", "sim", "on", "", None, 1.0]
)
def test_booleano_rejeita_outras_representacoes(entrada: object) -> None:
    with pytest.raises(ValidationError):
        _BOOLEANO.validate_python(entrada)


@pytest.mark.parametrize("entrada", [[], {}])
def test_booleano_rejeita_valor_nao_hashavel_com_erro_de_validacao(entrada: object) -> None:
    with pytest.raises(ValidationError):
        _BOOLEANO.validate_python(entrada)


def test_verdadeiro_e_falso_aceitam_somente_o_proprio_valor() -> None:
    assert _VERDADEIRO.validate_python("true") is True
    assert _FALSO.validate_python("false") is False
    for entrada in (False, "false", 1):
        with pytest.raises(ValidationError):
            _VERDADEIRO.validate_python(entrada)
    for entrada in (True, "true", 0):
        with pytest.raises(ValidationError):
            _FALSO.validate_python(entrada)


@pytest.mark.parametrize(
    "entrada",
    [
        "2026-01-01T00:00:00",
        datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None),
        "2026-01-01T00:00:00-03:00",
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-3))),
        "2026-01-01",
        "ontem",
    ],
)
def test_instante_rejeita_sem_fuso_ou_fora_de_utc(entrada: object) -> None:
    with pytest.raises(ValidationError):
        _INSTANTE.validate_python(entrada)


@pytest.mark.parametrize(
    "entrada",
    [
        "2026-01-01T03:00:00Z",
        "2026-01-01T03:00:00+00:00",
        datetime(2026, 1, 1, 3, tzinfo=UTC),
        datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(0), "Z0")),
    ],
)
def test_instante_aceita_utc_e_normaliza_o_fuso(entrada: object) -> None:
    instante = _INSTANTE.validate_python(entrada)
    assert instante == datetime(2026, 1, 1, 3, tzinfo=UTC)
    assert instante.tzinfo is UTC


def test_data_aceita_iso_e_rejeita_formato_local() -> None:
    assert _DATA.validate_python("2026-01-31") == date(2026, 1, 31)
    with pytest.raises(ValidationError):
        _DATA.validate_python("31/01/2026")


@pytest.mark.parametrize(
    ("valor", "motivo"), [("0301", None), (None, MotivoAusencia.VAZIO), (None, "DESCONHECIDO")]
)
def test_valor_normalizado_aceita_valor_ou_motivo(valor: str | None, motivo: object) -> None:
    normalizado = ValorNormalizado(bruto="  ", valor=valor, motivo=motivo)
    assert normalizado.bruto == "  "


@pytest.mark.parametrize(("valor", "motivo"), [(None, None), ("0301", MotivoAusencia.SENTINELA)])
def test_valor_normalizado_rejeita_valor_e_motivo_juntos_ou_ausentes(
    valor: str | None, motivo: MotivoAusencia | None
) -> None:
    with pytest.raises(ValidationError, match="valor_normalizado_exige_valor_ou_motivo"):
        ValorNormalizado(bruto="x", valor=valor, motivo=motivo)


def test_valor_normalizado_exige_bruto_declarado() -> None:
    with pytest.raises(ValidationError):
        ValorNormalizado.model_validate({"valor": "0301"})


@pytest.mark.parametrize(
    ("estado", "sha256"), [(EstadoDocumento.PRESERVADO, "a" * 64), (EstadoDocumento.PENDENTE, None)]
)
def test_docref_aceita_preservado_com_hash_e_pendente_sem_hash(
    estado: EstadoDocumento, sha256: str | None
) -> None:
    assert _docref(estado=estado, sha256=sha256).estado is estado


@pytest.mark.parametrize(
    ("estado", "sha256"), [(EstadoDocumento.PRESERVADO, None), (EstadoDocumento.PENDENTE, "a" * 64)]
)
def test_docref_rejeita_estado_incoerente_com_hash(
    estado: EstadoDocumento, sha256: str | None
) -> None:
    with pytest.raises(ValidationError, match="docref_estado_e_hash_incoerentes"):
        _docref(estado=estado, sha256=sha256)


def test_docref_nasce_a_confirmar_e_limita_trecho() -> None:
    assert _docref().confirmacao is Confirmacao.A_CONFIRMAR
    assert _docref(trecho="x" * 400).trecho == "x" * 400
    with pytest.raises(ValidationError):
        _docref(trecho="x" * 401)


def test_sha256_exige_hexadecimal_minusculo() -> None:
    with pytest.raises(ValidationError):
        FileRef(caminho="data/raw/x", sha256="A" * 64)


def test_contrato_e_imutavel() -> None:
    documento = _docref()
    with pytest.raises(ValidationError, match="frozen_instance"):
        documento.titulo = "outro"
    assert documento.titulo == "Manual técnico"


def test_contrato_rejeita_campo_extra() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _docref(observado_em="2026-01-01T00:00:00Z")


@pytest.mark.parametrize("contrato", _contratos(), ids=lambda contrato: contrato.__name__)
def test_todo_contrato_e_imutavel_e_proibe_campos_extras(contrato: type[ContratoBase]) -> None:
    assert contrato.model_config.get("frozen") is True
    assert contrato.model_config.get("extra") == "forbid"


@given(st.dictionaries(st.text(max_size=5), _JSON, max_size=6))
def test_hash_canonico_independe_da_ordem_das_chaves(conteudo: dict[str, object]) -> None:
    assert hash_canonico(_inverter_chaves(conteudo)) == hash_canonico(conteudo)


@given(st.lists(st.integers(), min_size=2, max_size=6, unique=True))
def test_hash_canonico_depende_da_ordem_das_listas(itens: list[int]) -> None:
    assert hash_canonico(itens) != hash_canonico(list(reversed(itens)))


def test_json_canonico_tem_forma_estavel() -> None:
    conteudo = {"b": [1, "ç"], "a": None}
    esperado = '{"a":null,"b":[1,"ç"]}'
    assert json_canonico(conteudo) == esperado
    assert hash_canonico(conteudo) == hashlib.sha256(esperado.encode("utf-8")).hexdigest()
