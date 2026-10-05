"""Métricas pareadas com denominadores explícitos (T11).

A população é a partição do split identificada pelos rótulos recebidos; o TESTE só é avaliado
no confirmatório. No confirmatório o método precisa ter um resultado, e só um, de toda a
população, ou a avaliação é recusada (`metrics_cobertura`); no exploratório a linha sem saída de
um método conta como abstenção desse método e as contagens vão nas notas. Toda a população fica
nos denominadores de cobertura.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import TYPE_CHECKING

from sustemporal.contracts.base import hash_canonico
from sustemporal.contracts.config import RuntimeConfig
from sustemporal.contracts.evaluation import EvaluationReport, TipoMetrica, ValorMetrica
from sustemporal.contracts.experiment import BootstrapSpec, ModoExecucao, Particao, Portao
from sustemporal.duck import conectar
from sustemporal.errors import FalhaOperacionalErro, PortaoRecusado
from sustemporal.evaluation.bootstrap import intervalo_diferenca, intervalo_razao
from sustemporal.evaluation.freeze_conferencia import verificar_congelamento_completo
from sustemporal.evaluation.metrics_calculo import (
    LinhaAvaliada,
    calcular_metricas,
    indicadores,
)
from sustemporal.evaluation.metrics_cobertura import (
    Cobertura,
    calcular_coberturas,
    exigir_cobertura_completa,
    notas_de_cobertura,
)
from sustemporal.evaluation.metrics_leitura import (
    ler_populacao,
    ler_situacoes,
    verificar_entrada,
)
from sustemporal.gates import DIR_DECISOES, exigir_portao

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from sustemporal.contracts import (
        DatasetRef,
        FreezeManifest,
        RunResult,
        SplitManifest,
    )
    from sustemporal.contracts.base import OrigemDados
    from sustemporal.evaluation.freeze_conferencia import EstadoAtual
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = ["PARES_PRIMARIOS", "ReferenciaCongelamento", "evaluate_runs"]

logger = logging.getLogger(__name__)

PARES_PRIMARIOS = (("M_TEMP", "B_ATEND"), ("M_TEMP", "B_PROC"))
_COM_INTERVALO = (
    "cobertura_rejeicoes",
    "cobertura_verificabilidade",
    "precisao_alertas",
    "falsos_alertas_aprovacoes",
)
_CASAS = Decimal("0.000001")
_SEM_CNES = "SEM_CNES"
_SEM_COMPETENCIA = "SEM_COMPETENCIA"
NOTAS = (
    (
        "populacao_alvo_estabelecimento: o bootstrap sorteia estabelecimentos (CNES) inteiros, "
        "preservando a trajetória mensal; não protege contra dependência entre estabelecimentos "
        "no mesmo mês"
    ),
    (
        "sensibilidade_blocos_temporais: sorteia competências inteiras; protege contra choques "
        "comuns do mês, não contra dependência dentro do estabelecimento"
    ),
    (
        "linhas_nao_independentes: nenhuma reamostragem trata linhas como independentes; "
        "registros sem CNES formam um único conglomerado SEM_CNES"
    ),
    (
        "associacao_de_resultado: métricas contra PA_INDICA medem concordância de resultado, "
        "não correção da causa"
    ),
    (
        "dominio_comum: rótulo binário e cnes, procedimento, cbo, competência de atendimento e "
        "instrumento presentes; definido sem o resultado dos métodos"
    ),
    (
        "rejeicao_sem_alerta: fora de escopo só com causa documentada na referência de anotação; "
        "o restante é causa indeterminada"
    ),
    (
        "diferenca_pareada: valor = (rejeições sinalizadas por A − por B) / rejeições; o "
        "numerador registrado é o das rejeições sinalizadas por A"
    ),
)


def _particao_dos_rotulos(split: SplitManifest, labels: DatasetRef) -> Particao:
    candidatas = [
        particao
        for particao, ref in (split.rotulos_por_particao or {}).items()
        if ref.dataset_id == labels.dataset_id and ref.caminho == labels.caminho
    ]
    if len(candidatas) != 1 or split.particoes is None:
        raise ValueError(
            f"rotulos_fora_do_split split={split.split_id} rotulos={labels.dataset_id}"
        )
    return candidatas[0]


def _exigir_congelamento_cumprido(
    runs: Sequence[RunResult], split: SplitManifest, congelamento: ReferenciaCongelamento
) -> None:
    manifesto, estado = congelamento.manifesto, congelamento.estado
    if manifesto is None or estado is None or manifesto.freeze_id != congelamento.freeze_id:
        raise PortaoRecusado(
            f"avaliacao_confirmatoria_sem_manifesto_do_freeze freeze={congelamento.freeze_id}"
        )
    estado_do_split = replace(estado, split=split)
    verificar_congelamento_completo(manifesto, estado_do_split, runs, congelamento.entradas)


def _modo(
    runs: Sequence[RunResult],
    split: SplitManifest,
    particao: Particao,
    congelamento: ReferenciaCongelamento | None,
) -> ModoExecucao:
    modos = {run.modo for run in runs}
    if len(modos) != 1:
        raise ValueError("avaliacao_com_modos_misturados")
    modo = modos.pop()
    if modo is ModoExecucao.EXPLORATORIO and particao is Particao.TESTE:
        raise PortaoRecusado("avaliacao_exploratoria_no_teste")
    if modo is not ModoExecucao.CONFIRMATORIO:
        return modo
    if particao is not Particao.TESTE or congelamento is None:
        raise PortaoRecusado(f"avaliacao_confirmatoria_fora_do_teste particao={particao}")
    freeze_id = congelamento.freeze_id
    if any(run.freeze_id != freeze_id for run in runs):
        raise PortaoRecusado(
            f"avaliacao_confirmatoria_com_execucao_de_outro_freeze freeze={freeze_id}"
        )
    exigir_portao(congelamento.decisoes, Portao.G2, freeze_id=freeze_id)
    _exigir_congelamento_cumprido(runs, split, congelamento)
    return modo


def _origem(runs: Sequence[RunResult], labels: DatasetRef) -> OrigemDados:
    origens = {run.origem_dados for run in runs} | {labels.origem_dados}
    if len(origens) != 1:
        raise ValueError("avaliacao_com_origens_misturadas")
    return origens.pop()


def _grupos(linhas: Sequence[LinhaAvaliada], por_competencia: bool) -> list[str]:
    if por_competencia:
        return [linha.competencia or _SEM_COMPETENCIA for linha in linhas]
    return [linha.cnes or _SEM_CNES for linha in linhas]


def _com_intervalos(
    metricas: list[ValorMetrica],
    linhas: Sequence[LinhaAvaliada],
    metodos: Sequence[str],
    spec: BootstrapSpec,
) -> list[ValorMetrica]:
    alvos = {f"{metodo}.{nome}": (metodo, nome) for metodo in metodos for nome in _COM_INTERVALO}
    grupos = _grupos(linhas, por_competencia=False)
    saida = []
    for metrica in metricas:
        if metrica.estrato != "TOTAL" or metrica.nome not in alvos:
            saida.append(metrica)
            continue
        nums, dens = indicadores(linhas, *alvos[metrica.nome])
        saida.append(metrica.model_copy(update={"ic": intervalo_razao(nums, dens, grupos, spec)}))
    return saida


def _diferencas(
    linhas: Sequence[LinhaAvaliada], pares: Sequence[tuple[str, str]], spec: BootstrapSpec
) -> list[ValorMetrica]:
    saida = []
    for a, b in pares:
        num_a, dens = indicadores(linhas, a, "cobertura_rejeicoes")
        num_b, _ = indicadores(linhas, b, "cobertura_rejeicoes")
        denominador = sum(dens)
        valor = None
        if denominador > 0:
            valor = (Decimal(sum(num_a) - sum(num_b)) / denominador).quantize(
                _CASAS, rounding=ROUND_HALF_EVEN
            )
        for estrato, por_competencia in (
            ("TOTAL", False),
            ("sensibilidade_blocos_temporais", True),
        ):
            grupos = _grupos(linhas, por_competencia)
            saida.append(
                ValorMetrica(
                    nome=f"diferenca.{a}_x_{b}.cobertura_rejeicoes",
                    tipo=TipoMetrica.ESTATISTICA,
                    estrato=estrato,
                    numerador=sum(num_a),
                    denominador=denominador,
                    valor=valor,
                    ic=intervalo_diferenca(num_a, num_b, dens, grupos, spec)
                    if valor is not None
                    else None,
                )
            )
    return saida


def _ler(
    runs: Sequence[RunResult],
    labels: DatasetRef,
    split: SplitManifest,
    particao: Particao,
    causas: Mapping[str, str],
) -> tuple[list[LinhaAvaliada], list[Cobertura]]:
    populacao = (split.particoes or {})[particao]
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        verificar_entrada(con, populacao)
        verificar_entrada(con, labels)
        base = ler_populacao(con, populacao, labels, causas)
        leitura = ler_situacoes(con, runs, particao)
    finally:
        con.close()
    linhas = [
        replace(
            linha,
            situacoes={
                m: s[linha.row_id] for m, s in leitura.situacoes.items() if linha.row_id in s
            },
        )
        for linha in base
    ]
    return linhas, calcular_coberturas((linha.row_id for linha in base), leitura)


def _exigir_cobertura(
    modo: ModoExecucao,
    coberturas: Sequence[Cobertura],
    congelamento: ReferenciaCongelamento | None,
) -> None:
    manifesto = congelamento.manifesto if congelamento else None
    if modo is ModoExecucao.CONFIRMATORIO and manifesto is not None:
        exigir_cobertura_completa(coberturas, manifesto)


def _metricas(
    linhas: Sequence[LinhaAvaliada], metodos: Sequence[str], spec: BootstrapSpec
) -> list[ValorMetrica]:
    pares = [par for par in PARES_PRIMARIOS if set(par) <= set(metodos)]
    metricas = calcular_metricas(linhas, metodos, pares=pares)
    return [*_com_intervalos(metricas, linhas, metodos, spec), *_diferencas(linhas, pares, spec)]


def _gravar_sem_sobrescrever(caminho: Path, relatorio: EvaluationReport) -> None:
    texto = relatorio.model_dump_json(indent=2)
    if caminho.exists():
        if caminho.read_text(encoding="utf-8") != texto:
            raise FalhaOperacionalErro(f"relatorio_existente_divergente caminho={caminho}")
        return
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("x", encoding="utf-8") as arquivo:
        arquivo.write(texto)


@dataclass(frozen=True)
class ReferenciaCongelamento:
    """Congelamento avaliado.

    No confirmatório, além da decisão G2 humana que abriu o teste, traz o manifesto carregado e o
    estado atual do avaliador (com a config confirmatória do congelamento), contra os quais o
    split avaliado e cada execução são conferidos.
    """

    freeze_id: str
    decisao_g2: str | None = None
    decisoes: Path = DIR_DECISOES
    manifesto: FreezeManifest | None = None
    estado: EstadoAtual | None = None
    entradas: Mapping[str, EntradaValidacao] | None = None


def _bootstrap(
    bootstrap: BootstrapSpec | None,
    modo: ModoExecucao,
    congelamento: ReferenciaCongelamento | None,
) -> BootstrapSpec:
    manifesto = congelamento.manifesto if congelamento else None
    if modo is not ModoExecucao.CONFIRMATORIO or manifesto is None:
        return bootstrap or BootstrapSpec()
    if bootstrap is not None and bootstrap != manifesto.bootstrap:
        raise PortaoRecusado(
            "avaliacao_confirmatoria_com_bootstrap_diferente_do_congelado "
            f"freeze={manifesto.freeze_id}"
        )
    return manifesto.bootstrap


def _id_do_relatorio(
    runs: Sequence[RunResult],
    labels: DatasetRef,
    split: SplitManifest,
    *,
    causas: Mapping[str, str],
    spec: BootstrapSpec,
    freeze_id: str | None,
) -> str:
    conteudo = {
        "runs": sorted(run.run_id for run in runs),
        "rotulos": labels.hash_logico,
        "split": split.split_id,
        "freeze": freeze_id,
        "causas": dict(sorted(causas.items())),
        "bootstrap": spec.model_dump(mode="json"),
    }
    return f"rep_{hash_canonico(conteudo)}"


def _notas(
    particao: Particao, spec: BootstrapSpec, coberturas: Sequence[Cobertura]
) -> tuple[str, ...]:
    return (
        *NOTAS,
        f"particao={particao.value}",
        f"reamostragens={spec.reamostragens}",
        *notas_de_cobertura(coberturas),
    )


def evaluate_runs(
    runs: list[RunResult],
    labels: DatasetRef,
    split: SplitManifest,
    out: Path,
    *,
    causas: Mapping[str, str] | None = None,
    bootstrap: BootstrapSpec | None = None,
    congelamento: ReferenciaCongelamento | None = None,
    relogio: Callable[[], datetime] | None = None,
) -> EvaluationReport:
    """Calcula as métricas do protocolo para as execuções comparadas.

    Raises:
        ValueError: sem execuções, rótulos fora do split, modos/origens misturados ou método
            repetido. PortaoRecusado: exploratório no TESTE; confirmatório fora dele, sem G2,
            sem manifesto e estado do avaliador, ou com bootstrap, split, estado ou execução
            incompatível com o congelamento, execução incompleta, sem método primário, que não
            cobre todos os registros do TESTE ou que repete o resultado de um (método, row_id).
        FalhaOperacionalErro: entrada ilegível ou diferente do `DatasetRef`.
    """
    if not runs:
        raise ValueError("avaliacao_sem_execucoes")
    particao = _particao_dos_rotulos(split, labels)
    freeze_id = congelamento.freeze_id if congelamento else None
    modo = _modo(runs, split, particao, congelamento)
    origem = _origem(runs, labels)
    spec = _bootstrap(bootstrap, modo, congelamento)
    linhas, coberturas = _ler(runs, labels, split, particao, causas or {})
    _exigir_cobertura(modo, coberturas, congelamento)
    relatorio = EvaluationReport(
        report_id=_id_do_relatorio(
            runs, labels, split, causas=causas or {}, spec=spec, freeze_id=freeze_id
        ),
        modo=modo,
        origem_dados=origem,
        freeze_id=freeze_id,
        decisao_g2=congelamento.decisao_g2 if congelamento else None,
        runs=tuple(run.run_id for run in runs),
        metricas=tuple(_metricas(linhas, [c.metodo for c in coberturas], spec)),
        notas=_notas(particao, spec, coberturas),
        criado_em=(relogio or (lambda: datetime.now(UTC)))(),
    )
    _gravar_sem_sobrescrever(out / f"{relatorio.report_id}.json", relatorio)
    logger.info("avaliacao_concluida report=%s particao=%s", relatorio.report_id, particao)
    return relatorio
