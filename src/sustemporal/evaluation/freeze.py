"""Congelamento do protocolo e conferência de compatibilidade com o manifesto (T11).

O manifesto é único por conteúdo (`freeze_id` deriva do conteúdo) e nunca é sobrescrito. O
`config_hash` congelado é a identidade do protocolo sem `modo` e `freeze_id`, de modo que a
config confirmatória que só abre o teste confere com a config congelada. Cada execução
confirmatória é conferida contra o manifesto: código, config, catálogo de regras, política e
entradas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.base import hash_canonico, hash_identidade
from sustemporal.contracts.experiment import (
    DecisaoPortao,
    FreezeManifest,
    ModoExecucao,
    Particao,
    Portao,
    TipoExecucao,
)
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro, PortaoRecusado
from sustemporal.evaluation.features import auditar_features
from sustemporal.gates import DIR_DECISOES, exigir_portao
from sustemporal.hashing import sha256_arquivo
from sustemporal.rules.catalog import carregar_esquema, catalogo_sha256
from sustemporal.runtime_info import ambiente, versao_codigo
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from decimal import Decimal

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

__all__ = [
    "COMPARACOES_PRIMARIAS",
    "METRICAS_PROTOCOLO",
    "Protocolo",
    "carregar_freeze",
    "congelar",
    "hash_protocolo",
    "referencia_decisao",
    "verificar_comparacoes_primarias",
    "verificar_compatibilidade",
    "verificar_execucao",
]

logger = logging.getLogger(__name__)

COMPARACOES_PRIMARIAS = ("M_TEMP_x_B_ATEND", "M_TEMP_x_B_PROC")
METRICAS_PROTOCOLO = (
    "cobertura_rejeicoes",
    "cobertura_verificabilidade",
    "precisao_alertas",
    "falsos_alertas_aprovacoes",
    "abstencao",
    "alerta_aprovacao_parcial",
    "rejeicoes_sem_alerta_fora_de_escopo_documentada",
    "rejeicoes_sem_alerta_causa_indeterminada",
    "divergencia_pareada",
    "diferenca_pareada_cobertura_rejeicoes",
)
_PREFIXO_DECISOES = "experiments/decisions"


def hash_protocolo(config: RunConfig) -> str:
    """Identidade da config sem `modo` e `freeze_id`, que mudam ao abrir o teste."""
    return hash_identidade(config, excluir={"modo", "freeze_id"})


def referencia_decisao(diretorio: Path, decisao: DecisaoPortao) -> str:
    """Caminho `experiments/decisions/<arquivo>` da decisão humana que liberou o portão.

    Raises:
        PortaoRecusado: nenhum arquivo do diretório contém a decisão.
    """
    for arquivo in sorted([*diretorio.glob("*.yaml"), *diretorio.glob("*.yml")]):
        if arquivo.name.startswith("MODELO_"):
            continue
        try:
            lida = DecisaoPortao.model_validate(carregar_yaml(arquivo))
        except (ValueError, OSError):
            continue
        if lida == decisao:
            return f"{_PREFIXO_DECISOES}/{arquivo.name}"
    raise PortaoRecusado(f"decisao_sem_arquivo portao={decisao.portao} diretorio={diretorio}")


@dataclass(frozen=True)
class Protocolo:
    """O que se congela: config, split, atributos, entradas, catálogos, regras e políticas.

    `regras` e `politicas` dão a identidade que cada execução que usa regras precisa repetir; sem
    elas o manifesto não as registra e a conferência recusa essas execuções.
    """

    config: RunConfig
    split: SplitManifest
    features: FeatureSpec
    dataset: DatasetRef
    rotulos: DatasetRef
    catalogos: Mapping[str, Path]
    margens: Mapping[str, Decimal] = field(default_factory=dict)
    regras: Sequence[RuleSpec] = ()
    politicas: Sequence[PoliticaTemporal] = ()


def congelar(
    protocolo: Protocolo,
    destino: Path,
    *,
    decisoes: Path = DIR_DECISOES,
    codigo: CodeVersion | None = None,
    relogio: Callable[[], datetime] | None = None,
    hoje: date | None = None,
) -> FreezeManifest:
    """Emite o manifesto único do protocolo; exige G0 humano liberado.

    Raises:
        PortaoRecusado: G0 ausente ou que não libera.
        ConfigInvalida: protocolo incoerente, com valor A_DEFINIR, código sujo, catálogo
            ausente ou política repetida com conteúdo diferente.
        FalhaOperacionalErro: já existe outro conteúdo sob o mesmo `freeze_id`.
    """
    g0 = exigir_portao(decisoes, Portao.G0, hoje=hoje)
    _exigir_coerencia(protocolo)
    raiz = Path.cwd()
    try:
        manifesto = FreezeManifest.criar(
            criado_em=(relogio or _agora)(),
            config_hash=hash_protocolo(protocolo.config),
            codigo=codigo if codigo is not None else versao_codigo(raiz),
            ambiente=ambiente(raiz),
            catalogos_sha256=_hashes_dos_catalogos(protocolo.catalogos),
            catalogo_regras_sha256=_hash_das_regras(protocolo.regras),
            politicas_sha256=_hashes_das_politicas(protocolo.politicas),
            datasets=(protocolo.dataset, protocolo.rotulos),
            split=protocolo.split,
            features=protocolo.features,
            bootstrap=protocolo.config.bootstrap,
            metricas=METRICAS_PROTOCOLO,
            comparacoes_primarias=COMPARACOES_PRIMARIAS,
            margens=dict(protocolo.margens),
            decisao_g0=referencia_decisao(decisoes, g0),
        )
    except ValidationError as erro:
        raise ConfigInvalida(f"congelamento_invalido erro={erro}") from erro
    _gravar(manifesto, destino)
    logger.info("protocolo_congelado freeze=%s destino=%s", manifesto.freeze_id, destino)
    return manifesto


def _agora() -> datetime:
    return datetime.now(UTC)


def _exigir_coerencia(protocolo: Protocolo) -> None:
    split = protocolo.split
    if split.rotulos_por_particao is None or split.particoes is None:
        raise ConfigInvalida(f"congelamento_split_sem_particoes split={split.split_id}")
    if split.dataset_hash != protocolo.dataset.hash_logico:
        raise ConfigInvalida(f"congelamento_split_de_outro_dataset split={split.split_id}")
    if protocolo.rotulos.schema_id != "sia_pa_rotulos.v1":
        raise ConfigInvalida(f"congelamento_rotulos_invalidos schema={protocolo.rotulos.schema_id}")
    esquemas = {carregar_esquema(a.schema_id) for a in protocolo.features.atributos}
    auditar_features(protocolo.features, esquemas)


def _hashes_dos_catalogos(catalogos: Mapping[str, Path]) -> dict[str, str]:
    ausentes = sorted(nome for nome, caminho in catalogos.items() if not Path(caminho).is_file())
    if ausentes or not catalogos:
        raise ConfigInvalida(f"congelamento_catalogo_ausente catalogos={','.join(ausentes)}")
    return {nome: sha256_arquivo(Path(caminho)) for nome, caminho in sorted(catalogos.items())}


def _hash_das_regras(regras: Sequence[RuleSpec]) -> str | None:
    return catalogo_sha256(list(regras)) if regras else None


def _hashes_das_politicas(politicas: Sequence[PoliticaTemporal]) -> dict[str, str] | None:
    hashes: dict[str, str] = {}
    for politica in politicas:
        conteudo = hash_canonico(politica.model_dump(mode="json"))
        if hashes.setdefault(politica.politica_id, conteudo) != conteudo:
            raise ConfigInvalida(f"congelamento_politica_repetida politica={politica.politica_id}")
    return hashes or None


def _gravar(manifesto: FreezeManifest, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{manifesto.freeze_id}.json"
    texto = manifesto.model_dump_json(indent=2)
    if caminho.exists():
        if caminho.read_text(encoding="utf-8") != texto:
            raise FalhaOperacionalErro(f"congelamento_existente_divergente caminho={caminho}")
        return
    with caminho.open("x", encoding="utf-8") as arquivo:
        arquivo.write(texto)


def carregar_freeze(diretorio: Path, freeze_id: str) -> FreezeManifest:
    """Manifesto `<diretorio>/<freeze_id>.json` cujo id confere com o conteúdo.

    Raises:
        ConfigInvalida: manifesto ausente, adulterado ou de outro `freeze_id`.
    """
    caminho = diretorio / f"{freeze_id}.json"
    if not caminho.is_file():
        raise ConfigInvalida(f"congelamento_ausente freeze={freeze_id} diretorio={diretorio}")
    try:
        manifesto = FreezeManifest.model_validate_json(caminho.read_text(encoding="utf-8"))
    except ValidationError as erro:
        raise ConfigInvalida(f"congelamento_invalido freeze={freeze_id}") from erro
    if manifesto.freeze_id != freeze_id:
        raise ConfigInvalida(f"congelamento_de_outro_id freeze={freeze_id}")
    return manifesto


def _hashes_congelados(manifesto: FreezeManifest) -> set[str]:
    congelado = manifesto.split
    permitidos = {d.hash_logico for d in manifesto.datasets}
    permitidos |= set(congelado.hash_por_particao.values())
    permitidos |= {d.hash_logico for d in (congelado.rotulos_por_particao or {}).values()}
    return permitidos


def _codigo_divergente(codigo: CodeVersion, manifesto: FreezeManifest) -> bool:
    return codigo.sujo or codigo.commit != manifesto.codigo.commit


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

    Raises:
        PortaoRecusado: `freeze_incompativel campos=...` com cada identidade divergente.
    """
    permitidos = _hashes_congelados(manifesto)
    divergencias = {
        "codigo": _codigo_divergente(codigo, manifesto),
        "split": split.split_id != manifesto.split.split_id,
        "features": features != manifesto.features,
        "config": hash_protocolo(config) != manifesto.config_hash,
        "entradas": any(d.hash_logico not in permitidos for d in datasets),
    }
    if campos := [nome for nome, divergente in divergencias.items() if divergente]:
        raise PortaoRecusado(
            f"freeze_incompativel campos={','.join(campos)} freeze={manifesto.freeze_id}"
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
