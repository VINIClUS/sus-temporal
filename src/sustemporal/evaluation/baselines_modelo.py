"""Codificação ajustada só no treino, regressão logística e limiar da calibração (T10)."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.linear_model import LogisticRegression

from sustemporal.contracts.experiment import Particao
from sustemporal.evaluation.features import NUMERICA

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sustemporal.contracts.experiment import FeatureSpec

__all__ = [
    "AUSENTE",
    "DESCONHECIDA",
    "NEGATIVO",
    "POSITIVO",
    "SEM_ROTULO",
    "Ajuste",
    "Codificador",
    "Linha",
    "Predicao",
    "ajustar",
    "prever",
]

DESCONHECIDA = "__DESCONHECIDA__"
AUSENTE = "__AUSENTE__"
FREQUENCIA_MINIMA = 2
C_REGULARIZACAO = 1.0
MAX_ITERACOES = 1000
LIMIAR_PADRAO = 0.5
POSITIVO = "NAO_APROVADO"
NEGATIVO = "APROVADO_TOTAL"
SEM_ROTULO = "SEM_ROTULO"
_CASAS_ESCORE = Decimal("1e-9")

Linha = dict[str, Any]
Predicao = tuple[str, str, str, Decimal, str]


def _token(valor: object, vocabulario: Sequence[str]) -> str:
    texto = AUSENTE if valor is None else str(valor)
    return texto if texto in vocabulario else DESCONHECIDA


def _vocabulario(valores: list[object]) -> tuple[str, ...]:
    contagem = Counter(AUSENTE if v is None else str(v) for v in valores)
    frequentes = {texto for texto, n in contagem.items() if n >= FREQUENCIA_MINIMA}
    return tuple(sorted(frequentes | {AUSENTE, DESCONHECIDA}))


def _numero(valor: object) -> float | None:
    return None if valor is None else float(str(valor))


@dataclass(frozen=True)
class Codificador:
    """Vocabulários, medianas, médias e escalas calculados só nas linhas de treino."""

    categoricos: tuple[str, ...]
    numericos: tuple[str, ...]
    vocabulario: dict[str, tuple[str, ...]]
    medianas: dict[str, float]
    medias: dict[str, float]
    escalas: dict[str, float]

    @classmethod
    def ajustar(cls, treino: list[Linha], features: FeatureSpec) -> Codificador:
        numericos = tuple(a.coluna for a in features.atributos if a.transformacao == NUMERICA)
        categoricos = tuple(a.coluna for a in features.atributos if a.coluna not in numericos)
        vocabulario = {c: _vocabulario([linha[c] for linha in treino]) for c in categoricos}
        medianas, medias, escalas = {}, {}, {}
        for coluna in numericos:
            valores = [_numero(linha[coluna]) for linha in treino]
            presentes = [x for x in valores if x is not None]
            medianas[coluna] = statistics.median(presentes) if presentes else 0.0
            imputados = [medianas[coluna] if x is None else x for x in valores] or [0.0]
            medias[coluna] = statistics.fmean(imputados)
            escalas[coluna] = statistics.pstdev(imputados) or 1.0
        return cls(categoricos, numericos, vocabulario, medianas, medias, escalas)

    def transformar(self, linhas: list[Linha]) -> tuple[np.ndarray, dict[str, int]]:
        """Matriz codificada e contagem de valores fora do vocabulário do treino."""
        colunas: list[np.ndarray] = []
        desconhecidas: dict[str, int] = {}
        for coluna in self.categoricos:
            vocabulario = self.vocabulario[coluna]
            tokens = [_token(linha[coluna], vocabulario) for linha in linhas]
            desconhecidas[coluna] = sum(
                1
                for linha, token in zip(linhas, tokens, strict=True)
                if token == DESCONHECIDA and linha[coluna] is not None
            )
            colunas.extend(np.array([t == v for t in tokens], dtype=float) for v in vocabulario)
        for coluna in self.numericos:
            valores = [_numero(linha[coluna]) for linha in linhas]
            ausente = np.array([v is None for v in valores], dtype=float)
            preenchidos = np.array([self.medianas[coluna] if v is None else v for v in valores])
            colunas.append((preenchidos - self.medias[coluna]) / self.escalas[coluna])
            colunas.append(ausente)
        matriz = np.column_stack(colunas) if colunas else np.zeros((len(linhas), 0))
        return matriz.reshape(len(linhas), -1), desconhecidas


@dataclass
class Ajuste:
    """Parâmetros ajustados em DESENVOLVIMENTO e limiar escolhido na CALIBRACAO."""

    codificador: Codificador
    modelo: LogisticRegression
    limiar: float
    classe_prevalente: str
    taxa_positiva_treino: float
    contagens_treino: dict[str, int]
    desconhecidas: dict[str, dict[str, int]] = field(default_factory=dict)
    notas: list[str] = field(default_factory=list)

    def parametros(self) -> dict[str, Any]:
        cod = self.codificador
        return {
            "ajustado_em": [Particao.DESENVOLVIMENTO.value],
            "limiar_ajustado_em": [Particao.CALIBRACAO.value],
            "vocabulario": {c: list(v) for c, v in cod.vocabulario.items()},
            "numericos": {
                c: {"mediana": cod.medianas[c], "media": cod.medias[c], "escala": cod.escalas[c]}
                for c in cod.numericos
            },
            "coeficientes": [float(x) for x in self.modelo.coef_.ravel()],
            "intercepto": float(self.modelo.intercept_[0]),
            "limiar": self.limiar,
            "classe_prevalente": self.classe_prevalente,
            "contagens_treino": self.contagens_treino,
            "desconhecidas": self.desconhecidas,
            "regularizacao": {"penalidade": "l2", "C": C_REGULARIZACAO},
            "balanceamento": "class_weight=balanced, pesos do treino",
            "frequencia_minima": FREQUENCIA_MINIMA,
            "notas": self.notas,
        }


def _binarias(linhas: list[Linha]) -> tuple[list[Linha], np.ndarray]:
    usadas = [linha for linha in linhas if linha["rotulo"] in {POSITIVO, NEGATIVO}]
    return usadas, np.array([1 if linha["rotulo"] == POSITIVO else 0 for linha in usadas])


def _limiar(escores: np.ndarray, alvo: np.ndarray) -> float | None:
    """Limiar de maior índice de Youden; empate fica com o limiar mais alto."""
    positivos, negativos = int(alvo.sum()), int((alvo == 0).sum())
    if positivos == 0 or negativos == 0:
        return None
    ordem = np.argsort(-escores, kind="stable")
    ordenados, rotulos = escores[ordem], alvo[ordem]
    youden = np.cumsum(rotulos) / positivos - np.cumsum(1 - rotulos) / negativos
    fim_de_grupo = np.append(ordenados[1:] != ordenados[:-1], True)
    candidatos = np.flatnonzero(fim_de_grupo)
    return float(ordenados[candidatos[int(np.argmax(youden[candidatos]))]])


def _escores(ajuste: Ajuste, linhas: list[Linha]) -> np.ndarray:
    if not linhas:
        return np.zeros(0)
    matriz, _ = ajuste.codificador.transformar(linhas)
    return np.asarray(ajuste.modelo.predict_proba(matriz)[:, 1])


def ajustar(dados: dict[Particao, list[Linha]], features: FeatureSpec, semente: int) -> Ajuste:
    """Ajusta codificador e modelo no desenvolvimento e o limiar na calibração.

    Raises:
        ValueError: desenvolvimento sem as duas classes binárias.
    """
    treino = dados[Particao.DESENVOLVIMENTO]
    usadas, alvo = _binarias(treino)
    codificador = Codificador.ajustar(usadas, features)
    if len(set(alvo.tolist())) < 2:
        raise ValueError(f"treino_sem_ambas_as_classes linhas_binarias={len(usadas)}")
    modelo = LogisticRegression(
        C=C_REGULARIZACAO, class_weight="balanced", max_iter=MAX_ITERACOES, random_state=semente
    )
    modelo.fit(codificador.transformar(usadas)[0], alvo)
    contagens = Counter(str(linha["rotulo"] or SEM_ROTULO) for linha in treino)
    positivos = int(alvo.sum())
    ajuste = Ajuste(
        codificador=codificador,
        modelo=modelo,
        limiar=LIMIAR_PADRAO,
        classe_prevalente=POSITIVO if positivos > len(alvo) - positivos else NEGATIVO,
        taxa_positiva_treino=positivos / len(alvo),
        contagens_treino={**dict(sorted(contagens.items())), "usadas_no_ajuste": len(usadas)},
    )
    calibracao, alvo_cal = _binarias(dados.get(Particao.CALIBRACAO, []))
    limiar = _limiar(_escores(ajuste, calibracao), alvo_cal)
    if limiar is None:
        ajuste.notas.append("limiar_padrao: calibracao sem as duas classes binarias")
    else:
        ajuste.limiar = limiar
    return ajuste


def escore_decimal(valor: float) -> Decimal:
    return Decimal(repr(valor)).quantize(_CASAS_ESCORE, rounding=ROUND_HALF_EVEN)


def prever(ajuste: Ajuste, dados: dict[Particao, list[Linha]]) -> list[Predicao]:
    """Linhas (row_id, metodo, particao, escore, resultado) do B_ML e do controle trivial."""
    saida: list[Predicao] = []
    trivial = "ALERTA" if ajuste.classe_prevalente == POSITIVO else "SEM_ALERTA"
    escore_trivial = escore_decimal(ajuste.taxa_positiva_treino)
    for particao, linhas in dados.items():
        _, desconhecidas = ajuste.codificador.transformar(linhas)
        ajuste.desconhecidas[particao.value] = desconhecidas
        for linha, escore in zip(linhas, _escores(ajuste, linhas), strict=True):
            resultado = "ALERTA" if escore >= ajuste.limiar else "SEM_ALERTA"
            row_id, valor = str(linha["row_id"]), escore_decimal(float(escore))
            saida.append((row_id, "B_ML", particao.value, valor, resultado))
            saida.append((row_id, "CONTROLE_TRIVIAL", particao.value, escore_trivial, trivial))
    return saida
