"""Congelamento do protocolo (T11).

O manifesto é único por conteúdo (`freeze_id` deriva do conteúdo) e nunca é sobrescrito. O
`config_hash` congelado é a identidade do protocolo sem `modo` e `freeze_id`, de modo que a
config confirmatória que só abre o teste confere com a config congelada. A conferência do
manifesto contra o estado atual e contra cada execução está em `freeze_conferencia`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from sustemporal.contracts.base import hash_canonico, hash_identidade
from sustemporal.contracts.experiment import DecisaoPortao, FreezeManifest, Particao, Portao
from sustemporal.errors import ConfigInvalida, FalhaOperacionalErro, PortaoRecusado
from sustemporal.evaluation.features import auditar_features
from sustemporal.evaluation.freeze_entrada import identidades_da_entrada
from sustemporal.gates import DIR_DECISOES, exigir_portao
from sustemporal.hashing import sha256_arquivo
from sustemporal.rules.catalog import carregar_esquema, catalogo_sha256
from sustemporal.runtime_info import RAIZ_DO_PACOTE, ambiente, versao_codigo
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
        SplitManifest,
    )
    from sustemporal.contracts.temporal import PoliticaTemporal
    from sustemporal.rules.entrada import EntradaValidacao

__all__ = [
    "COMPARACOES_PRIMARIAS",
    "METRICAS_PROTOCOLO",
    "Protocolo",
    "carregar_freeze",
    "congelar",
    "hash_das_regras",
    "hash_protocolo",
    "hashes_das_politicas",
    "hashes_dos_catalogos",
    "referencia_decisao",
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

    `catalogos` são os que `config.catalogos` declara (os digests são recalculados por esses
    caminhos na conferência). `regras` e `politicas` dão a identidade que cada execução que usa
    regras precisa repetir; sem elas o manifesto não as registra e a conferência recusa essas
    execuções. `insumos` traz, por `politica_id`, a entrada de validação (`entrada_validacao.json`)
    sobre o TESTE que as execuções dessa política devem usar: o manifesto grava a identidade de
    cada campo dela (`freeze_entrada`); sem insumos a conferência recusa toda execução de regras.
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
    insumos: Mapping[str, EntradaValidacao] = field(default_factory=dict)


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
            ausente ou que a config não declara, política repetida com conteúdo diferente ou
            insumos que não são os da partição TESTE.
        FalhaOperacionalErro: já existe outro conteúdo sob o mesmo `freeze_id`.
    """
    g0 = exigir_portao(decisoes, Portao.G0, hoje=hoje)
    _exigir_coerencia(protocolo)
    entradas_validacao = _entradas_validacao(protocolo)
    raiz = RAIZ_DO_PACOTE
    try:
        manifesto = FreezeManifest.criar(
            criado_em=(relogio or _agora)(),
            config_hash=hash_protocolo(protocolo.config),
            codigo=codigo if codigo is not None else versao_codigo(raiz),
            ambiente=ambiente(raiz),
            catalogos_sha256=hashes_dos_catalogos(protocolo.catalogos),
            catalogo_regras_sha256=hash_das_regras(protocolo.regras),
            politicas_sha256=hashes_das_politicas(protocolo.politicas),
            datasets=(protocolo.dataset, protocolo.rotulos),
            split=protocolo.split,
            features=protocolo.features,
            bootstrap=protocolo.config.bootstrap,
            metricas=METRICAS_PROTOCOLO,
            comparacoes_primarias=COMPARACOES_PRIMARIAS,
            margens=dict(protocolo.margens),
            decisao_g0=referencia_decisao(decisoes, g0),
            entradas_validacao=entradas_validacao,
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
    declarados = {nome: Path(caminho) for nome, caminho in protocolo.config.catalogos.items()}
    if declarados != {nome: Path(caminho) for nome, caminho in protocolo.catalogos.items()}:
        raise ConfigInvalida(f"congelamento_catalogos_fora_da_config config={sorted(declarados)}")
    esquemas = {carregar_esquema(a.schema_id) for a in protocolo.features.atributos}
    auditar_features(protocolo.features, esquemas)
    _exigir_insumos_do_teste(protocolo)


def _exigir_insumos_do_teste(protocolo: Protocolo) -> None:
    teste = protocolo.split.hash_por_particao[Particao.TESTE]
    de_outra = sorted(p for p, e in protocolo.insumos.items() if e.dataset.hash_logico != teste)
    if de_outra:
        raise ConfigInvalida(
            f"congelamento_insumos_de_outra_populacao politicas={','.join(de_outra)}"
        )


def _entradas_validacao(protocolo: Protocolo) -> dict[str, dict[str, str]] | None:
    """Identidade de cada campo da entrada de validação, por política; None sem insumos.

    A política resolvida que o `validate` grava vale a do catálogo congelado (`politicas_sha256`):
    a da entrada, se vier, tem de ser essa.
    """
    catalogo = hashes_das_politicas(protocolo.politicas) or {}
    congeladas = {}
    for politica_id, entrada in sorted(protocolo.insumos.items()):
        campos = identidades_da_entrada(entrada)
        if politica_id in catalogo:
            if entrada.politica is not None and campos["politica"] != catalogo[politica_id]:
                raise ConfigInvalida(
                    f"congelamento_insumos_com_politica_diferente politica={politica_id}"
                )
            campos["politica"] = catalogo[politica_id]
        congeladas[politica_id] = campos
    return congeladas or None


def hashes_dos_catalogos(catalogos: Mapping[str, Path]) -> dict[str, str]:
    """SHA-256 de cada catálogo por nome; `congelar` e a conferência usam esta função.

    Raises:
        ConfigInvalida: sem catálogos ou com algum arquivo ausente.
    """
    ausentes = sorted(nome for nome, caminho in catalogos.items() if not Path(caminho).is_file())
    if ausentes or not catalogos:
        raise ConfigInvalida(f"congelamento_catalogo_ausente catalogos={','.join(ausentes)}")
    return {nome: sha256_arquivo(Path(caminho)) for nome, caminho in sorted(catalogos.items())}


def hash_das_regras(regras: Sequence[RuleSpec]) -> str | None:
    """Identidade do catálogo de regras (a que as execuções registram); None sem regras."""
    return catalogo_sha256(list(regras)) if regras else None


def hashes_das_politicas(politicas: Sequence[PoliticaTemporal]) -> dict[str, str] | None:
    """Hash canônico de cada política por `politica_id`; None sem políticas.

    Raises:
        ConfigInvalida: política repetida com conteúdo diferente.
    """
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


def _ler_manifesto(caminho: Path, freeze_id: str) -> FreezeManifest | None:
    """O manifesto de `caminho`; None se o arquivo não existe.

    `ValueError` cobre o UTF-8 inválido, o JSON truncado e o contrato (`ValidationError`).
    """
    try:
        if not caminho.is_file():
            return None
        return FreezeManifest.model_validate_json(caminho.read_text(encoding="utf-8"))
    except OSError as erro:
        motivo = type(erro).__name__
        raise ConfigInvalida(f"congelamento_ilegivel freeze={freeze_id} motivo={motivo}") from erro
    except ValueError as erro:
        raise ConfigInvalida(f"congelamento_invalido freeze={freeze_id}") from erro


def carregar_freeze(diretorio: Path, freeze_id: str) -> FreezeManifest:
    """Manifesto `<diretorio>/<freeze_id>.json` cujo id confere com o conteúdo.

    Raises:
        ConfigInvalida: manifesto ausente, que o sistema nega ler (`congelamento_ilegivel`),
            adulterado (UTF-8 inválido, JSON truncado ou fora do contrato) ou de outro
            `freeze_id`.
    """
    manifesto = _ler_manifesto(diretorio / f"{freeze_id}.json", freeze_id)
    if manifesto is None:
        raise ConfigInvalida(f"congelamento_ausente freeze={freeze_id} diretorio={diretorio}")
    if manifesto.freeze_id != freeze_id:
        raise ConfigInvalida(f"congelamento_de_outro_id freeze={freeze_id}")
    return manifesto
