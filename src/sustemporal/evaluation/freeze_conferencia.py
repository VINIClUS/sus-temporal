"""Conferência do FreezeManifest contra o estado atual e contra cada execução (T11).

Todo campo do manifesto está em `CAMPOS_DO_MANIFESTO`, classificado como conferido contra o
estado atual do avaliador, contra cada execução ou informativo, com o motivo. Um teste percorre
`FreezeManifest.model_fields` e falha se um campo novo ficar sem classificação; código e
ambiente têm subcampos informativos (`SUBCAMPOS_INFORMATIVOS`) e todo o resto deles é conferido.
`verificar_congelamento_completo` é a única comparação: estado em `freeze_incompativel
campos=...`, execução em `run_incompativel_com_congelamento run=... campo=...`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.contracts.experiment import (
    Ambiente,
    EstadoExecucao,
    FreezeManifest,
    ModoExecucao,
    Particao,
    TipoExecucao,
)
from sustemporal.errors import ConfigInvalida, PortaoRecusado
from sustemporal.evaluation.freeze import (
    COMPARACOES_PRIMARIAS,
    METRICAS_PROTOCOLO,
    hash_das_regras,
    hash_protocolo,
    hashes_das_politicas,
    hashes_dos_catalogos,
    ids_nao_populacionais,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from sustemporal.contracts import (
        CodeVersion,
        DatasetRef,
        FeatureSpec,
        RuleSpec,
        RunConfig,
        RunResult,
        SplitManifest,
    )
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = [
    "CAMPOS_DO_MANIFESTO",
    "SUBCAMPOS_INFORMATIVOS",
    "Campo",
    "EstadoAtual",
    "ambiente_divergente",
    "campos_sem_classificacao",
    "declara_outras_particoes",
    "entradas_do_congelamento",
    "verificar_comparacoes_primarias",
    "verificar_congelamento_completo",
    "verificar_execucao",
    "verificar_execucao_concluida",
]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Campo:
    """Como um campo do manifesto é conferido; sem `estado` nem `execucao`, é informativo.

    `estado` e `execucao` são os nomes que a divergência leva em `freeze_incompativel campos=` e
    em `run_incompativel_com_congelamento campo=` (ou `metodos`, a falta de execução de método).
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
    "auxiliares": Campo(execucao="auxiliares"),
    "snapshots": Campo(execucao="snapshots"),
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
    return {nome for nome in nomes if nome not in CAMPOS_DO_MANIFESTO}


@dataclass(frozen=True)
class EstadoAtual:
    """O que o avaliador observa agora; `regras` e `politicas` só valem para quem as usa.

    Os catálogos vêm de `config.catalogos`, os mesmos caminhos que o congelamento usou.
    """

    config: RunConfig
    split: SplitManifest
    features: FeatureSpec
    datasets: Sequence[DatasetRef]
    codigo: CodeVersion
    ambiente: Ambiente
    regras: Sequence[RuleSpec] | None = None
    politicas: Sequence[PoliticaTemporal] | None = None


def _informativos(modelo: str) -> set[str]:
    prefixo = f"{modelo}."
    nomes = (nome for nome in SUBCAMPOS_INFORMATIVOS if nome.startswith(prefixo))
    return {nome.removeprefix(prefixo) for nome in nomes}


def ambiente_divergente(congelado: Ambiente, observado: Ambiente) -> bool:
    """Ambientes que diferem em qualquer campo que não seja informativo (hoje, a plataforma)."""
    conferidos = set(Ambiente.model_fields) - _informativos("ambiente")
    return any(getattr(congelado, nome) != getattr(observado, nome) for nome in conferidos)


def _hashes_congelados(manifesto: FreezeManifest) -> set[str]:
    congelado = manifesto.split
    permitidos = {d.hash_logico for d in manifesto.datasets}
    permitidos |= set(congelado.hash_por_particao.values())
    permitidos |= {d.hash_logico for d in (congelado.rotulos_por_particao or {}).values()}
    return permitidos


def _codigo_divergente(codigo: CodeVersion, manifesto: FreezeManifest) -> bool:
    return codigo.sujo or codigo.commit != manifesto.codigo.commit


def _catalogos_divergentes(manifesto: FreezeManifest, config: RunConfig) -> bool:
    caminhos = {nome: Path(caminho) for nome, caminho in config.catalogos.items()}
    try:
        return hashes_dos_catalogos(caminhos) != manifesto.catalogos_sha256
    except ConfigInvalida as erro:
        logger.warning("catalogos_nao_conferidos erro=%s", erro)
        return True


def _regras_divergentes(manifesto: FreezeManifest, regras: Sequence[RuleSpec] | None) -> bool:
    return regras is not None and hash_das_regras(regras) != manifesto.catalogo_regras_sha256


def _politicas_divergentes(
    manifesto: FreezeManifest, politicas: Sequence[PoliticaTemporal] | None
) -> bool:
    if politicas is None:
        return False
    try:
        return hashes_das_politicas(politicas) != manifesto.politicas_sha256
    except ConfigInvalida:
        return True


def _divergencias_do_estado(manifesto: FreezeManifest, estado: EstadoAtual) -> dict[str, bool]:
    permitidos = _hashes_congelados(manifesto)
    return {
        "codigo": _codigo_divergente(estado.codigo, manifesto),
        "ambiente": ambiente_divergente(manifesto.ambiente, estado.ambiente),
        "split": estado.split != manifesto.split,
        "features": estado.features != manifesto.features,
        "config": hash_protocolo(estado.config) != manifesto.config_hash,
        "catalogos": _catalogos_divergentes(manifesto, estado.config),
        "catalogo": _regras_divergentes(manifesto, estado.regras),
        "politica": _politicas_divergentes(manifesto, estado.politicas),
        "bootstrap": estado.config.bootstrap != manifesto.bootstrap,
        "metricas": manifesto.metricas != METRICAS_PROTOCOLO,
        "comparacoes": manifesto.comparacoes_primarias != COMPARACOES_PRIMARIAS,
        "entradas": any(d.hash_logico not in permitidos for d in estado.datasets),
    }


def verificar_congelamento_completo(
    manifesto: FreezeManifest,
    estado: EstadoAtual,
    runs: Sequence[RunResult] = (),
    entradas: Mapping[str, EntradaValidacao] | None = None,
) -> None:
    """Confere o manifesto inteiro contra o estado atual e, se dadas, contra cada execução.

    O split é comparado por inteiro (o `split_id` não deriva do conteúdo), os catálogos pelo
    digest recalculado e o ambiente pelo Python e pelas dependências. Com `runs`, cada execução
    é conferida e precisa ter concluído sem falhas, e o conjunto precisa trazer os métodos das
    comparações primárias.

    Raises:
        PortaoRecusado: `freeze_incompativel campos=...` para o estado; para as execuções,
            `run_incompativel_com_congelamento`, `execucao_incompleta_no_confirmatorio` e
            `avaliacao_confirmatoria_sem_metodo_das_comparacoes_primarias`.
    """
    divergencias = _divergencias_do_estado(manifesto, estado)
    if campos := [nome for nome, divergente in divergencias.items() if divergente]:
        raise PortaoRecusado(
            f"freeze_incompativel campos={','.join(campos)} freeze={manifesto.freeze_id}"
        )
    for run in runs:
        entrada = (entradas or {}).get(run.run_id)
        verificar_execucao(manifesto, run, config=estado.config, entrada=entrada)
        verificar_execucao_concluida(run)
    if runs:
        verificar_comparacoes_primarias(manifesto, runs)


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


def _sem_insumos_a_conferir(manifesto: FreezeManifest, run: RunResult) -> bool:
    """Baseline não usa regras; política desconhecida já diverge em `politica`."""
    return run.tipo is TipoExecucao.BASELINE_ML or _politica_divergente(manifesto, run)


def _auxiliares_divergentes(manifesto: FreezeManifest, run: RunResult) -> bool:
    if _sem_insumos_a_conferir(manifesto, run):
        return False
    congelados = (manifesto.auxiliares or {}).get(run.politica_id or "")
    atuais = ids_nao_populacionais(run.entradas, manifesto.datasets)
    return congelados is None or set(atuais) != set(congelados)


def _snapshots_divergentes(manifesto: FreezeManifest, run: RunResult) -> bool:
    if _sem_insumos_a_conferir(manifesto, run):
        return False
    congelado = (manifesto.snapshots or {}).get(run.politica_id or "")
    return congelado is None or run.snapshot_set_id != congelado


def _hashes_das_entradas_congeladas(manifesto: FreezeManifest, run: RunResult) -> set[str]:
    esquemas = {d.schema_id for d in manifesto.datasets}
    return {d.hash_logico for d in run.entradas if d.schema_id in esquemas}


def entradas_do_congelamento(manifesto: FreezeManifest, run: RunResult) -> bool:
    """A execução traz entrada dos esquemas congelados e todas são conteúdo congelado.

    É a pertença da execução ao split do congelamento, sem exigir o TESTE: a execução
    exploratória lê a CALIBRACAO.
    """
    hashes = _hashes_das_entradas_congeladas(manifesto, run)
    return bool(hashes) and hashes <= _hashes_congelados(manifesto)


def declara_outras_particoes(manifesto: FreezeManifest, run: RunResult) -> bool:
    """A execução traz como entrada a população de alguma partição congelada além do TESTE."""
    outras = {h for p, h in manifesto.split.hash_por_particao.items() if p is not Particao.TESTE}
    return any(d.hash_logico in outras for d in run.entradas)


def _entradas_divergentes(manifesto: FreezeManifest, run: RunResult) -> bool:
    teste = manifesto.split.hash_por_particao[Particao.TESTE]
    hashes = _hashes_das_entradas_congeladas(manifesto, run)
    return teste not in hashes or not hashes <= _hashes_congelados(manifesto)


def _divergencias_da_entrada(
    manifesto: FreezeManifest, run: RunResult, entrada: EntradaValidacao | None
) -> dict[str, bool]:
    raise NotImplementedError("freeze_entrada")


def verificar_execucao(
    manifesto: FreezeManifest,
    run: RunResult,
    *,
    config: RunConfig,
    entrada: EntradaValidacao | None = None,
) -> None:
    """Recusa a execução cuja identidade registrada difere da congelada.

    `config` é a config confirmatória do congelamento: o protocolo dela confere com o manifesto
    (`hash_protocolo`) e o `config_hash` da execução é o dela, com `modo` e `freeze_id`. O
    ambiente (Python e dependências) é o congelado, para toda execução. Catálogo de regras,
    política, auxiliares e snapshots valem para toda execução, menos a de baseline
    (`BASELINE_ML`), que não usa regras. Entre as entradas, as `sia_pa.v1` e de rótulos são a
    população e a da partição TESTE precisa estar entre elas (o baseline pode trazer outras
    partições). O resto delas (auxiliares, seleções e cobertura) e o `snapshot_set_id` são os
    congelados para o `politica_id` da execução; sem insumos congelados para a política, diverge.

    Raises:
        PortaoRecusado: `run_incompativel_com_congelamento run=... campo=...`, com cada identidade
            divergente na ordem código, ambiente, config, catálogo, política, entradas,
            auxiliares e snapshots.
    """
    divergencias = {
        "codigo": _codigo_divergente(run.codigo, manifesto),
        "ambiente": ambiente_divergente(manifesto.ambiente, run.ambiente),
        "config": _config_divergente(manifesto, run, config),
        "catalogo": _catalogo_divergente(manifesto, run),
        "politica": _politica_divergente(manifesto, run),
        "entradas": _entradas_divergentes(manifesto, run),
        "auxiliares": _auxiliares_divergentes(manifesto, run),
        "snapshots": _snapshots_divergentes(manifesto, run),
    }
    if manifesto.entradas_validacao is not None:
        divergencias.update(_divergencias_da_entrada(manifesto, run, entrada))
    if campos := [nome for nome, divergente in divergencias.items() if divergente]:
        raise PortaoRecusado(
            f"run_incompativel_com_congelamento run={run.run_id} campo={','.join(campos)} "
            f"freeze={manifesto.freeze_id}"
        )
