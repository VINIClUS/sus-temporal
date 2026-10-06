"""Avaliador de referência de V(r, g, S, p) em Python puro (docs/method/model.md §3, §4, §6).

Independente do motor SQL: depende só da biblioteca padrão e dos contratos. Clareza acima de
desempenho; serve de oráculo para o teste diferencial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.rules import (
    Aplicabilidade,
    EstadoAvaliacao,
    FamiliaRegra,
    MotivoInconclusao,
    RequisitoFonte,
    ResultadoRegistro,
    RuleSpec,
    decidir_estado,
)
from sustemporal.contracts.temporal import BaseTemporal, EstadoSelecao, TipoPolitica, TipoTempo
from sustemporal.rules.reference_dominio import DOMINIO_DO_CAMPO, ConjuntoAuxiliar, escopo

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

__all__ = [
    "AvaliacaoReferencia",
    "CenarioReferencia",
    "ConjuntoAuxiliar",
    "agregar_referencia",
    "avaliar_referencia",
]

_M = MotivoInconclusao

_SCHEMA_DA_FAMILIA: dict[FamiliaRegra, str] = {
    FamiliaRegra.PROCEDIMENTO_CBO: "sigtap_proc_ocupacao.v1",
    FamiliaRegra.ESTABELECIMENTO_CBO: "cnes_estab_cbo.v1",
    FamiliaRegra.INSTRUMENTO_REGISTRO: "sigtap_proc_registro.v1",
    FamiliaRegra.VIGENCIA_PROCEDIMENTO: "sigtap_procedimento.v1",
}

_REGISTRO_DO_INSTRUMENTO = {"C": "01", "I": "02", "P": "06", "S": "07", "A": "08", "B": "09"}

_MOTIVO_DA_SELECAO: dict[EstadoSelecao, MotivoInconclusao | None] = {
    EstadoSelecao.SELECIONADA: None,
    EstadoSelecao.AUSENTE: _M.ARQUIVO_AUSENTE,
    EstadoSelecao.AMBIGUA: _M.VERSAO_AMBIGUA,
    EstadoSelecao.INCOMPLETA: _M.COBERTURA_INSUFICIENTE,
    EstadoSelecao.EM_QUARENTENA: _M.ARQUIVO_EM_QUARENTENA,
    EstadoSelecao.FORA_DO_CORTE: _M.FORA_DO_CORTE,
    EstadoSelecao.NAO_RESOLVIDA: _M.VIGENCIA_NAO_RESOLVIDA,
}

_COMPETENCIA_DO_TIPO: dict[TipoTempo, str] = {
    TipoTempo.ATENDIMENTO: "competencia_atendimento",
    TipoTempo.PROCESSAMENTO: "competencia_processamento",
}
_COMPETENCIA_DA_BASE: dict[str, str] = {
    BaseTemporal.ATENDIMENTO: "competencia_atendimento",
    BaseTemporal.PROCESSAMENTO: "competencia_processamento",
}


@dataclass(frozen=True)
class CenarioReferencia:
    """Insumos de uma execução: registros, auxiliares, seleção, cobertura e integridade."""

    colunas_registros: frozenset[str]
    registros: tuple[Mapping[str, str | None], ...]
    auxiliares: tuple[ConjuntoAuxiliar, ...]
    selecoes: tuple[Mapping[str, object], ...]
    cobertura: tuple[Mapping[str, str | None], ...] | None
    integridade: Mapping[str, str]
    politica_tipo: TipoPolitica


@dataclass(frozen=True)
class AvaliacaoReferencia:
    """Resultado de V(r, g, S, p) para um par (registro, regra)."""

    row_id: str
    rule_id: str
    estado: EstadoAvaliacao
    aplicabilidade: Aplicabilidade
    insumos_completos: bool
    incompatibilidade_demonstrada: bool | None
    motivos: tuple[MotivoInconclusao, ...]


@dataclass(frozen=True)
class _Desfecho:
    estado: EstadoAvaliacao
    aplicabilidade: Aplicabilidade
    incompatibilidade: bool | None = None
    motivos: frozenset[MotivoInconclusao] = field(default_factory=frozenset)


@dataclass(frozen=True)
class _Indices:
    selecoes: dict[tuple[str, str, str], Mapping[str, object]]
    auxiliares: dict[str, ConjuntoAuxiliar]
    cobertura: dict[tuple[str, str, str, str], Mapping[str, str | None]] | None


def _indexar[K, V](itens: Iterable[V], chave: Callable[[V], K], erro: str) -> dict[K, V]:
    indice: dict[K, V] = {}
    for item in itens:
        if (k := chave(item)) in indice:
            raise ValueError(f"{erro} chave={k}")
        indice[k] = item
    return indice


def _chave_selecao(linha: Mapping[str, object]) -> tuple[str, str, str]:
    return str(linha["row_id"]), str(linha["rule_id"]), str(linha["fonte"])


def _chave_cobertura(linha: Mapping[str, str | None]) -> tuple[str, str, str, str]:
    campos = ("familia_regra", "instrumento", "competencia", "base_temporal")
    familia, instrumento, competencia, base = (str(linha[c]) for c in campos)
    return familia, instrumento, competencia, base


def _valor(
    cenario: CenarioReferencia, registro: Mapping[str, str | None], campo: str
) -> str | None:
    """Valor do campo; ausente, nulo ou fora do domínio do código (§3) conta como nulo."""
    if campo not in cenario.colunas_registros:
        return None
    valor = registro.get(campo)
    dominio = DOMINIO_DO_CAMPO.get(campo)
    if valor is None or dominio is None:
        return valor
    return valor if dominio.fullmatch(valor) else None


def _texto_igual(valor: object, codigo: str | None) -> bool:
    return isinstance(valor, str) and codigo is not None and valor == codigo


def _requisitos_auxiliares(regra: RuleSpec) -> tuple[RequisitoFonte, ...]:
    return tuple(r for r in regra.requisitos_fonte if r.fonte is not FamiliaFonte.SIA_PA)


def _requisito_da_familia(regra: RuleSpec) -> RequisitoFonte:
    if regra.familia not in _SCHEMA_DA_FAMILIA:
        raise ValueError(f"familia_sem_referencia regra={regra.rule_id} familia={regra.familia}")
    esperado = _SCHEMA_DA_FAMILIA[regra.familia]
    candidatos = [r for r in _requisitos_auxiliares(regra) if r.schema_id == esperado]
    if len(candidatos) != 1:
        raise ValueError(f"regra_sem_fonte_da_familia regra={regra.rule_id} schema={esperado}")
    return candidatos[0]


def _nao_aplicavel() -> _Desfecho:
    return _Desfecho(EstadoAvaliacao.NAO_APLICAVEL, Aplicabilidade.NAO_APLICAVEL_DEMONSTRADA)


def _desconhecida(motivos: frozenset[MotivoInconclusao]) -> _Desfecho:
    return _Desfecho(EstadoAvaliacao.INCONCLUSIVO, Aplicabilidade.DESCONHECIDA, motivos=motivos)


def _inconclusivo(motivos: frozenset[MotivoInconclusao]) -> _Desfecho:
    return _Desfecho(EstadoAvaliacao.INCONCLUSIVO, Aplicabilidade.APLICAVEL, motivos=motivos)


_SEM_CAMPO = frozenset({_M.CAMPO_INSUFICIENTE, _M.APLICABILIDADE_DESCONHECIDA})
_EM_QUARENTENA = frozenset({_M.APLICABILIDADE_DESCONHECIDA, _M.ARQUIVO_EM_QUARENTENA})


def _registro_em_quarentena(cenario: CenarioReferencia, registro: Mapping[str, str | None]) -> bool:
    """Passo 0: versão SIA-PA do próprio registro em QUARENTENA_*."""
    artefato = _valor(cenario, registro, "artifact_id")
    integridade = cenario.integridade.get(artefato) if artefato is not None else None
    return integridade is not None and integridade.startswith("QUARENTENA_")


def _aplicabilidade(
    cenario: CenarioReferencia, registro: Mapping[str, str | None], regra: RuleSpec
) -> _Desfecho | None:
    """Passos 1 a 4; None significa APLICAVEL."""
    instrumento = _valor(cenario, registro, "instrumento")
    if instrumento is None:
        return _desconhecida(_SEM_CAMPO)
    if instrumento not in regra.instrumentos:
        return _nao_aplicavel()
    vigencia = regra.vigencia
    if vigencia is None:
        return None
    coluna = _COMPETENCIA_DO_TIPO.get(vigencia.referente_a)
    competencia = None if coluna is None else _valor(cenario, registro, coluna)
    if competencia is None:
        return _desconhecida(_SEM_CAMPO)
    depois_do_inicio = vigencia.inicio is None or competencia >= vigencia.inicio
    antes_do_fim = vigencia.fim is None or competencia <= vigencia.fim
    if not (depois_do_inicio and antes_do_fim):
        return _nao_aplicavel()
    return None


def _motivos_de_campos(
    cenario: CenarioReferencia, registro: Mapping[str, str | None], regra: RuleSpec
) -> set[MotivoInconclusao]:
    motivos: set[MotivoInconclusao] = set()
    if any(_valor(cenario, registro, c) is None for c in regra.campos_necessarios):
        motivos.add(_M.CAMPO_INSUFICIENTE)
    instrumento = _valor(cenario, registro, "instrumento")
    fora_do_mapa = instrumento not in _REGISTRO_DO_INSTRUMENTO
    if regra.familia is FamiliaRegra.INSTRUMENTO_REGISTRO and fora_do_mapa:
        motivos.add(_M.CAMPO_INSUFICIENTE)
    return motivos


def _versoes(selecao: Mapping[str, object]) -> frozenset[str]:
    artefatos = selecao.get("artifact_ids") or ()
    if not isinstance(artefatos, tuple | list | frozenset | set):
        raise ValueError("selecao_artifact_ids_invalido")
    return frozenset(str(a) for a in artefatos)


@dataclass
class _Insumos:
    motivos: set[MotivoInconclusao]
    escopos: dict[str, tuple[Mapping[str, object], ...]] = field(default_factory=dict)
    selecoes: dict[str, Mapping[str, object]] = field(default_factory=dict)
    versoes: set[str] = field(default_factory=set)


def _insumos(
    cenario: CenarioReferencia,
    indices: _Indices,
    registro: Mapping[str, str | None],
    regra: RuleSpec,
) -> _Insumos:
    """Passos 5 a 8 (passo 0 já tratado na aplicabilidade)."""
    insumos = _Insumos(motivos=_motivos_de_campos(cenario, registro, regra))
    if cenario.politica_tipo is TipoPolitica.NAO_RESOLVIDA:
        insumos.motivos.add(_M.POLITICA_NAO_RESOLVIDA)
    row_id = str(registro["row_id"])
    for requisito in _requisitos_auxiliares(regra):
        selecao = indices.selecoes.get((row_id, regra.rule_id, requisito.fonte.value))
        if selecao is None:
            insumos.motivos.add(_M.VIGENCIA_NAO_RESOLVIDA)
            continue
        motivo_selecao = _MOTIVO_DA_SELECAO[EstadoSelecao(str(selecao["estado"]))]
        if motivo_selecao is not None:
            insumos.motivos.add(motivo_selecao)
            continue
        versoes = _versoes(selecao)
        conjunto = indices.auxiliares.get(requisito.schema_id)
        motivo, linhas = escopo(conjunto, requisito, selecao, versoes, cenario.integridade)
        if motivo is not None:
            insumos.motivos.add(motivo)
            continue
        insumos.escopos[requisito.schema_id] = linhas
        insumos.selecoes[requisito.schema_id] = selecao
        insumos.versoes |= versoes
    return insumos


_ENCONTRADO = "ENCONTRADO"
_AUSENCIA = "AUSENCIA"
_DESCONHECIDA = "DESCONHECIDA"

_SEM_LINHA_DA_CHAVE: dict[FamiliaRegra, str | MotivoInconclusao] = {
    FamiliaRegra.PROCEDIMENTO_CBO: _DESCONHECIDA,
    FamiliaRegra.ESTABELECIMENTO_CBO: _M.COBERTURA_INSUFICIENTE,
    FamiliaRegra.INSTRUMENTO_REGISTRO: _M.COBERTURA_INSUFICIENTE,
}

type _Teste = Callable[[object], bool]
type _LeitorCampo = Callable[[str], str | None]


def _igual(codigo: str | None) -> _Teste:
    return lambda valor: _texto_igual(valor, codigo)


def _vinculos_positivos(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and valor > 0


def _chave(regra: RuleSpec, campo: _LeitorCampo) -> tuple[tuple[str, _Teste], ...]:
    """Colunas da chave da família (§4) com o teste de igualdade ao valor do registro."""
    familia = regra.familia
    procedimento = ("co_procedimento", _igual(campo("procedimento")))
    if familia is FamiliaRegra.PROCEDIMENTO_CBO:
        return procedimento, ("co_ocupacao", _igual(campo("cbo")))
    if familia is FamiliaRegra.ESTABELECIMENTO_CBO:
        cnes = ("cnes", _igual(campo("cnes")))
        return cnes, ("cbo", _igual(campo("cbo"))), ("n_vinculos", _vinculos_positivos)
    if familia is FamiliaRegra.INSTRUMENTO_REGISTRO:
        registro = _REGISTRO_DO_INSTRUMENTO.get(campo("instrumento") or "")
        return procedimento, ("co_registro", _igual(registro))
    if familia is FamiliaRegra.VIGENCIA_PROCEDIMENTO:
        return (procedimento,)
    raise ValueError(f"familia_sem_referencia regra={regra.rule_id} familia={familia}")


def _casa(linha: Mapping[str, object], chave: tuple[tuple[str, _Teste], ...]) -> bool:
    return all(teste(linha.get(coluna)) for coluna, teste in chave)


def _casa_com_nulo(linha: Mapping[str, object], chave: tuple[tuple[str, _Teste], ...]) -> bool:
    valores = [(linha.get(coluna), teste) for coluna, teste in chave]
    com_nulo = any(valor is None for valor, _ in valores)
    return com_nulo and all(valor is None or teste(valor) for valor, teste in valores)


def _predicado(
    regra: RuleSpec, escopo: Sequence[Mapping[str, object]], campo: _LeitorCampo
) -> str | MotivoInconclusao:
    """Passo 10: predicado existencial da família sobre Esc(r, g, f)."""
    chave = _chave(regra, campo)
    if any(_casa(linha, chave) for linha in escopo):
        return _ENCONTRADO
    if any(_casa_com_nulo(linha, chave) for linha in escopo):
        return _M.CAMPO_INSUFICIENTE
    coluna, pertence = chave[0]
    sem_linha = _SEM_LINHA_DA_CHAVE.get(regra.familia)
    if sem_linha is not None and not any(pertence(linha.get(coluna)) for linha in escopo):
        return sem_linha
    return _AUSENCIA


def _ausencia_sustentada(
    indices: _Indices, chave: tuple[str, str | None, str | None, object]
) -> bool:
    """Passo 11: cobertura DISPONIVEL na chave (familia, instrumento, Q(r), base)."""
    familia, instrumento, competencia, base = chave
    if indices.cobertura is None or instrumento is None or competencia is None or base is None:
        return False
    linha = indices.cobertura.get((familia, instrumento, competencia, str(base)))
    return linha is not None and linha.get("estado") == "DISPONIVEL"


def _sem_deslocamento(selecao: Mapping[str, object], campo: _LeitorCampo) -> bool:
    """Passo 11: a seleção consulta a própria competência base do registro (deslocamento 0)."""
    coluna = _COMPETENCIA_DA_BASE.get(str(selecao.get("base")))
    competencia = None if coluna is None else campo(coluna)
    return competencia is not None and selecao.get("competencia_requerida") == competencia


def _versoes_com_linha(insumos: _Insumos) -> bool:
    """Passo 11: toda versão selecionada tem ao menos uma linha no conjunto auxiliar."""
    for schema, linhas in insumos.escopos.items():
        presentes = {linha.get("artifact_id") for linha in linhas}
        if not _versoes(insumos.selecoes[schema]) <= presentes:
            return False
    return True


def _decidir_predicado(
    cenario: CenarioReferencia,
    indices: _Indices,
    registro: Mapping[str, str | None],
    regra: RuleSpec,
    insumos: _Insumos,
) -> _Desfecho:
    """Passos 10 e 11, só com insumos completos."""
    schema = _requisito_da_familia(regra).schema_id
    campo: _LeitorCampo = partial(_valor, cenario, registro)
    resultado = _predicado(regra, insumos.escopos[schema], campo)
    if resultado == _ENCONTRADO:
        return _Desfecho(EstadoAvaliacao.CONFORME, Aplicabilidade.APLICAVEL, False)
    if resultado == _DESCONHECIDA:
        return _desconhecida(frozenset({_M.APLICABILIDADE_DESCONHECIDA}))
    if isinstance(resultado, MotivoInconclusao):
        return _inconclusivo(frozenset({resultado}))
    selecao = insumos.selecoes[schema]
    chave = (
        regra.familia.value,
        campo("instrumento"),
        campo("competencia_processamento"),
        selecao.get("base"),
    )
    integras = all(cenario.integridade.get(a) == "OK" for a in insumos.versoes)
    sustentada = _ausencia_sustentada(indices, chave) and _sem_deslocamento(selecao, campo)
    if integras and _versoes_com_linha(insumos) and sustentada:
        return _Desfecho(EstadoAvaliacao.VIOLACAO, Aplicabilidade.APLICAVEL, True)
    return _inconclusivo(frozenset({_M.COBERTURA_INSUFICIENTE}))


def _avaliar_par(
    cenario: CenarioReferencia,
    indices: _Indices,
    registro: Mapping[str, str | None],
    regra: RuleSpec,
) -> _Desfecho:
    if _registro_em_quarentena(cenario, registro):
        return _desconhecida(_EM_QUARENTENA)
    desfecho = _aplicabilidade(cenario, registro, regra)
    if desfecho is not None:
        return desfecho
    insumos = _insumos(cenario, indices, registro, regra)
    if insumos.motivos:
        return _inconclusivo(frozenset(insumos.motivos))
    return _decidir_predicado(cenario, indices, registro, regra, insumos)


def _montar(row_id: str, rule_id: str, desfecho: _Desfecho) -> AvaliacaoReferencia:
    completos = desfecho.motivos <= {_M.APLICABILIDADE_DESCONHECIDA}
    motivos = tuple(sorted(desfecho.motivos, key=lambda motivo: motivo.value))
    conferido = decidir_estado(
        desfecho.aplicabilidade, completos, desfecho.incompatibilidade, motivos
    )
    if conferido is not desfecho.estado:
        raise RuntimeError(
            f"estado_divergente row={row_id} regra={rule_id} "
            f"referencia={desfecho.estado} contrato={conferido}"
        )
    return AvaliacaoReferencia(
        row_id=row_id,
        rule_id=rule_id,
        estado=desfecho.estado,
        aplicabilidade=desfecho.aplicabilidade,
        insumos_completos=completos,
        incompatibilidade_demonstrada=desfecho.incompatibilidade,
        motivos=motivos,
    )


def _validar_entradas(cenario: CenarioReferencia, regras: Sequence[RuleSpec]) -> None:
    row_ids = [str(registro["row_id"]) for registro in cenario.registros]
    if len(set(row_ids)) != len(row_ids):
        raise ValueError("registro_repetido")
    rule_ids = [regra.rule_id for regra in regras]
    if len(set(rule_ids)) != len(rule_ids):
        raise ValueError("regra_repetida")
    for regra in regras:
        _requisito_da_familia(regra)


def avaliar_referencia(
    cenario: CenarioReferencia, regras: Sequence[RuleSpec]
) -> list[AvaliacaoReferencia]:
    """Uma avaliação por (registro, regra), ordenada por (row_id, rule_id)."""
    _validar_entradas(cenario, regras)
    indices = _Indices(
        selecoes=_indexar(cenario.selecoes, _chave_selecao, "selecao_repetida"),
        auxiliares=_indexar(
            cenario.auxiliares, lambda c: c.schema_id, "conjunto_auxiliar_repetido"
        ),
        cobertura=None
        if cenario.cobertura is None
        else _indexar(cenario.cobertura, _chave_cobertura, "cobertura_repetida"),
    )
    avaliacoes = []
    for registro in cenario.registros:
        row_id = str(registro["row_id"])
        for regra in regras:
            desfecho = _avaliar_par(cenario, indices, registro, regra)
            avaliacoes.append(_montar(row_id, regra.rule_id, desfecho))
    return sorted(avaliacoes, key=lambda a: (a.row_id, a.rule_id))


def _resultado(estados: Sequence[EstadoAvaliacao]) -> ResultadoRegistro:
    if EstadoAvaliacao.VIOLACAO in estados:
        return ResultadoRegistro.ALERTA
    if EstadoAvaliacao.INCONCLUSIVO in estados:
        return ResultadoRegistro.ABSTENCAO
    if EstadoAvaliacao.CONFORME in estados:
        return ResultadoRegistro.SEM_VIOLACAO_VERIFICADA
    return ResultadoRegistro.ABSTENCAO


def agregar_referencia(avaliacoes: Sequence[AvaliacaoReferencia]) -> dict[str, ResultadoRegistro]:
    """Resultado por row_id conforme §6 (ALERTA, SEM_VIOLACAO_VERIFICADA ou ABSTENCAO)."""
    estados: dict[str, list[EstadoAvaliacao]] = {}
    vistos: set[tuple[str, str]] = set()
    for avaliacao in avaliacoes:
        chave = (avaliacao.row_id, avaliacao.rule_id)
        if chave in vistos:
            raise ValueError(f"avaliacao_repetida row={chave[0]} regra={chave[1]}")
        vistos.add(chave)
        estados.setdefault(avaliacao.row_id, []).append(avaliacao.estado)
    return {row_id: _resultado(lista) for row_id, lista in sorted(estados.items())}
