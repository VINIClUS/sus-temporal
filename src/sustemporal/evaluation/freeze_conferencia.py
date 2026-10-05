"""Conferência do FreezeManifest contra o estado atual e contra cada execução (T11).

Todo campo do manifesto está em `CAMPOS_DO_MANIFESTO`, classificado como conferido contra o
estado atual do avaliador, contra cada execução ou informativo, com o motivo. Um teste percorre
`FreezeManifest.model_fields` e falha se um campo novo ficar sem classificação.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sustemporal.contracts.experiment import (
    EstadoExecucao,
    FreezeManifest,
    ModoExecucao,
    Particao,
    TipoExecucao,
)
from sustemporal.errors import PortaoRecusado
from sustemporal.evaluation.freeze import hash_protocolo

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sustemporal.contracts import (
        Ambiente,
        CodeVersion,
        DatasetRef,
        FeatureSpec,
        RuleSpec,
        RunConfig,
        RunResult,
        SplitManifest,
    )
    from sustemporal.contracts.temporal import PoliticaTemporal

__all__ = [
    "CAMPOS_DO_MANIFESTO",
    "SUBCAMPOS_INFORMATIVOS",
    "Campo",
    "EstadoAtual",
    "ambiente_divergente",
    "campos_sem_classificacao",
    "verificar_comparacoes_primarias",
    "verificar_compatibilidade",
    "verificar_congelamento_completo",
    "verificar_execucao",
    "verificar_execucao_concluida",
    "verificar_split_congelado",
]


@dataclass(frozen=True)
class Campo:
    """Como um campo do manifesto é conferido; sem `estado` nem `execucao`, é informativo.

    `estado` e `execucao` são os nomes que a divergência leva em `freeze_incompativel campos=` e
    em `run_incompativel_com_congelamento campo=`.
    """

    estado: str | None = None
    execucao: str | None = None
    motivo: str = ""


CAMPOS_DO_MANIFESTO: dict[str, Campo] = {
    "freeze_id": Campo(motivo="derivado do conteúdo, recomputado ao carregar (`carregar_freeze`)"),
    "criado_em": Campo(motivo="instante do congelamento; entra no id, sem par no estado atual"),
    "config_hash": Campo(estado="config", execucao="config"),
    "codigo": Campo(estado="codigo", execucao="codigo"),
    "ambiente": Campo(estado="ambiente", execucao="ambiente"),
    "catalogos_sha256": Campo(estado="catalogos"),
    "datasets": Campo(estado="entradas", execucao="entradas"),
    "split": Campo(estado="split"),
    "features": Campo(estado="features"),
    "bootstrap": Campo(estado="bootstrap"),
    "metricas": Campo(estado="metricas"),
    "comparacoes_primarias": Campo(estado="comparacoes", execucao="metodos"),
    "margens": Campo(motivo="a avaliação não usa margens de relevância prática (pendência T11 #2)"),
    "decisao_g0": Campo(
        motivo="G0 só autoriza congelar (exigido em `congelar`); no teste vale o G2 do `freeze_id`"
    ),
    "catalogo_regras_sha256": Campo(estado="catalogo", execucao="catalogo"),
    "politicas_sha256": Campo(estado="politica", execucao="politica"),
}

SUBCAMPOS_INFORMATIVOS = {
    "codigo.versao_pacote": "coberto por `ambiente.pacotes` (`sus-temporal`)",
    "codigo.diff_sha256": "só existe em código sujo, que o manifesto recusa",
    "ambiente.plataforma": (
        "inclui a versão do kernel ou da compilação do sistema, que muda sem mudar as versões "
        "travadas por `uv.lock`"
    ),
}


def campos_sem_classificacao(nomes: Iterable[str]) -> set[str]:
    """Campos de `nomes` que `CAMPOS_DO_MANIFESTO` não classifica."""
    raise NotImplementedError


@dataclass(frozen=True)
class EstadoAtual:
    """O que o avaliador observa agora; `regras` e `politicas` só valem para quem as usa."""

    config: RunConfig
    split: SplitManifest
    features: FeatureSpec
    datasets: Sequence[DatasetRef]
    codigo: CodeVersion
    ambiente: Ambiente
    regras: Sequence[RuleSpec] | None = None
    politicas: Sequence[PoliticaTemporal] | None = None


def ambiente_divergente(congelado: Ambiente, observado: Ambiente) -> bool:
    """Ambientes que diferem em qualquer campo que não seja informativo."""
    raise NotImplementedError


def verificar_congelamento_completo(
    manifesto: FreezeManifest, estado: EstadoAtual, runs: Sequence[RunResult] = ()
) -> None:
    """Confere o manifesto inteiro contra o estado atual e, se dadas, contra cada execução."""
    raise NotImplementedError


def _hashes_congelados(manifesto: FreezeManifest) -> set[str]:
    congelado = manifesto.split
    permitidos = {d.hash_logico for d in manifesto.datasets}
    permitidos |= set(congelado.hash_por_particao.values())
    permitidos |= {d.hash_logico for d in (congelado.rotulos_por_particao or {}).values()}
    return permitidos


def _codigo_divergente(codigo: CodeVersion, manifesto: FreezeManifest) -> bool:
    return codigo.sujo or codigo.commit != manifesto.codigo.commit


def _split_divergente(split: SplitManifest, manifesto: FreezeManifest) -> bool:
    return split != manifesto.split


def verificar_compatibilidade(
    manifesto: FreezeManifest,
    *,
    config: RunConfig,
    split: SplitManifest,
    features: FeatureSpec,
    datasets: Sequence[DatasetRef],
    codigo: CodeVersion,
) -> None:
    """Recusa código, split, atributos, config ou entradas fora do congelamento.

    O split é comparado por inteiro, não só pelo `split_id`, que não deriva do conteúdo.

    Raises:
        PortaoRecusado: `freeze_incompativel campos=...` com cada identidade divergente.
    """
    permitidos = _hashes_congelados(manifesto)
    divergencias = {
        "codigo": _codigo_divergente(codigo, manifesto),
        "split": _split_divergente(split, manifesto),
        "features": features != manifesto.features,
        "config": hash_protocolo(config) != manifesto.config_hash,
        "entradas": any(d.hash_logico not in permitidos for d in datasets),
    }
    if campos := [nome for nome, divergente in divergencias.items() if divergente]:
        raise PortaoRecusado(
            f"freeze_incompativel campos={','.join(campos)} freeze={manifesto.freeze_id}"
        )


def verificar_split_congelado(manifesto: FreezeManifest, split: SplitManifest) -> None:
    """Recusa o split de conteúdo diferente do congelado, mesmo com o mesmo `split_id`.

    A população e os rótulos que a avaliação lê vêm do split, e o id não deriva do conteúdo.

    Raises:
        PortaoRecusado: `split_incompativel_com_congelamento split=... freeze=...`
    """
    if _split_divergente(split, manifesto):
        raise PortaoRecusado(
            f"split_incompativel_com_congelamento split={split.split_id} "
            f"freeze={manifesto.freeze_id}"
        )


def verificar_execucao_concluida(run: RunResult) -> None:
    """Recusa, no confirmatório, a execução que não concluiu ou que registrou falhas.

    O motor grava saídas avaliáveis também em execução PARCIAL ou FALHOU, e a leitura trataria o
    que faltou como abstenção do método.

    Raises:
        PortaoRecusado: `execucao_incompleta_no_confirmatorio run=... estado=... falhas=...`
    """
    if run.estado is not EstadoExecucao.CONCLUIDA or run.falhas > 0:
        raise PortaoRecusado(
            f"execucao_incompleta_no_confirmatorio run={run.run_id} estado={run.estado.value} "
            f"falhas={run.falhas}"
        )


def verificar_comparacoes_primarias(manifesto: FreezeManifest, runs: Sequence[RunResult]) -> None:
    """Recusa a avaliação sem execução de algum método das comparações primárias congeladas.

    Raises:
        PortaoRecusado: `avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias metodos=...`
            com os métodos sem execução.
    """
    exigidos = {metodo for nome in manifesto.comparacoes_primarias for metodo in nome.split("_x_")}
    presentes = {run.metodo.value for run in runs if run.metodo is not None}
    if faltam := sorted(exigidos - presentes):
        raise PortaoRecusado(
            "avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias "
            f"metodos={','.join(faltam)} freeze={manifesto.freeze_id}"
        )


def _config_divergente(manifesto: FreezeManifest, run: RunResult, config: RunConfig) -> bool:
    protocolo_confere = hash_protocolo(config) == manifesto.config_hash
    abertura = (config.modo, config.freeze_id)
    abre_o_teste = abertura == (ModoExecucao.CONFIRMATORIO, manifesto.freeze_id)
    return not (protocolo_confere and abre_o_teste and run.config_hash == config.config_hash)


def _catalogo_divergente(manifesto: FreezeManifest, run: RunResult) -> bool:
    if run.tipo is TipoExecucao.BASELINE_ML:
        return False
    congelado = manifesto.catalogo_regras_sha256
    return congelado is None or run.catalogo_regras_sha256 != congelado


def _politica_divergente(manifesto: FreezeManifest, run: RunResult) -> bool:
    if run.tipo is TipoExecucao.BASELINE_ML:
        return False
    return run.politica_id is None or run.politica_id not in (manifesto.politicas_sha256 or {})


def _entradas_divergentes(manifesto: FreezeManifest, run: RunResult) -> bool:
    esquemas = {d.schema_id for d in manifesto.datasets}
    congeladas = [d for d in run.entradas if d.schema_id in esquemas]
    permitidos = _hashes_congelados(manifesto)
    teste = manifesto.split.hash_por_particao[Particao.TESTE]
    sem_o_teste = not any(d.hash_logico == teste for d in congeladas)
    return sem_o_teste or any(d.hash_logico not in permitidos for d in congeladas)


def verificar_execucao(manifesto: FreezeManifest, run: RunResult, *, config: RunConfig) -> None:
    """Recusa a execução cuja identidade registrada difere da congelada.

    `config` é a config confirmatória do congelamento: o protocolo dela confere com o manifesto
    (`hash_protocolo`) e o `config_hash` da execução é o dela, com `modo` e `freeze_id`. Catálogo
    de regras e política valem para toda execução, menos a de baseline (`BASELINE_ML`), que não
    usa regras. Só as entradas `sia_pa.v1` e de rótulos são congeladas, e a população da
    partição TESTE precisa estar entre elas (o baseline pode trazer outras partições); auxiliares,
    seleções e cobertura não entram no manifesto.

    Raises:
        PortaoRecusado: `run_incompativel_com_congelamento run=... campo=...`, com cada identidade
            divergente na ordem código, config, catálogo, política e entradas.
    """
    divergencias = {
        "codigo": _codigo_divergente(run.codigo, manifesto),
        "config": _config_divergente(manifesto, run, config),
        "catalogo": _catalogo_divergente(manifesto, run),
        "politica": _politica_divergente(manifesto, run),
        "entradas": _entradas_divergentes(manifesto, run),
    }
    if campos := [nome for nome, divergente in divergencias.items() if divergente]:
        raise PortaoRecusado(
            f"run_incompativel_com_congelamento run={run.run_id} campo={','.join(campos)} "
            f"freeze={manifesto.freeze_id}"
        )
