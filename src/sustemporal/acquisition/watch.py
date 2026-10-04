"""Observação de republicações em janela móvel (T13).

Cada execução observa de novo os arquivos da janela, inclusive sem mudança: toda tentativa vira
observação no manifesto. A comparação com a versão observada antes é por multiconjunto de linhas
(`acquisition.comparacao`). A cadência (semanal) é do agendador externo.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.comparacao import ComparacaoVersoes, ResultadoComparacao
from sustemporal.acquisition.fetch import agora_utc, fetch_source
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import LayoutSpec
from sustemporal.contracts.artifacts import ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.temporal import CompetenciaArquivo
from sustemporal.yamlio import carregar_yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence
    from datetime import datetime

    from sustemporal.acquisition.sources import FonteCatalogo
    from sustemporal.acquisition.transport import Transporte
    from sustemporal.contracts import ArtifactObservation, ArtifactVersion, SourceRequest
    from sustemporal.contracts.artifacts import ChaveArtefato
    from sustemporal.contracts.config import RunConfig

__all__ = [
    "LEIAUTE_PA_PADRAO",
    "NOME_RELATORIO",
    "RECORTE_FIM",
    "RECORTE_INICIO",
    "JanelaIncompleta",
    "carregar_leiaute_pa",
    "chave_de_comparacao",
    "chaves_sumidas",
    "classificar_chave",
    "competencias_da_janela",
    "gravar_relatorio",
    "linhas_do_relatorio",
    "nao_conclusiva",
    "observe_updates",
    "resumir_linhas",
    "resumir_vigilancia",
    "sumida",
    "versoes_anteriores",
]

logger = logging.getLogger(__name__)

LEIAUTE_PA_PADRAO = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "sia_pa.yaml"
NOME_RELATORIO = "vigilancia.jsonl"
_MESES_PROCURADOS = 120
RECORTE_INICIO = CompetenciaArquivo("201801")
RECORTE_FIM = CompetenciaArquivo("202512")

Chave = tuple[object, str | None, str | None, str | None, str | None]


def observe_updates(
    requests: list[SourceRequest],
    store: Path,
    *,
    rede_permitida: bool = False,
    relogio: Callable[[], datetime] = agora_utc,
    transportes: Mapping[str, Transporte] | None = None,
    manifesto: Path | None = None,
) -> list[ArtifactObservation]:
    """Observa cada requisição e preserva também tentativas sem mudança.

    Nada é pulado por já ter sido obtido: os mesmos bytes viram nova observação da mesma versão.
    """
    observacoes = [
        fetch_source(
            requisicao,
            store,
            rede_permitida=rede_permitida,
            relogio=relogio,
            transportes=transportes,
            manifesto=manifesto,
        )
        for requisicao in requests
    ]
    obtidas = sum(o.resultado is ResultadoTentativa.OBTIDO for o in observacoes)
    logger.info("vigilancia_observada requisicoes=%d obtidas=%d", len(observacoes), obtidas)
    return observacoes


def competencias_da_janela(
    item: FonteCatalogo, uf: str, nomes: Iterable[str], janela: int, referencia: datetime
) -> list[CompetenciaArquivo]:
    """As `janela` competências mais recentes com arquivo listado, dentro do recorte do estudo.

    O recorte 2018–2025 é restrição do AGENTS.md: a busca parte do menor entre o mês de
    `referencia` e `RECORTE_FIM` e nunca desce abaixo de `RECORTE_INICIO`. Depois de 2025-12 a
    janela para de andar; observar além do recorte é decisão humana (pendência T13-6).
    """
    listados = sorted(set(nomes))
    mes_da_referencia = CompetenciaArquivo(f"{referencia.year:04d}{referencia.month:02d}")
    competencia = min(mes_da_referencia, RECORTE_FIM)
    achadas: list[CompetenciaArquivo] = []
    for _ in range(_MESES_PROCURADOS):
        if competencia < RECORTE_INICIO or len(achadas) == janela:
            break
        expressao = item.expressao(uf, competencia)
        if any(expressao.fullmatch(nome) for nome in listados):
            achadas.append(competencia)
        competencia = competencia.deslocar(-1)
    return sorted(achadas)


def chaves_sumidas(
    anteriores: Iterable[Chave],
    atuais: set[Chave],
    fonte: object,
    janela: list[CompetenciaArquivo],
) -> list[Chave]:
    """Chaves já acompanhadas da fonte que não estão nas requisições da listagem atual.

    Só contam as competências do início da janela atual em diante: as mais antigas saíram da
    janela porque chegaram competências novas, não porque sumiram. Janela vazia não aponta
    nada: conjunto vazio nunca vira ausência (fica como janela incompleta).
    """
    if not janela:
        return []
    inicio = janela[0].valor
    return sorted(
        (c for c in anteriores if c[0] is fonte and c not in atuais and (c[2] or "") >= inicio),
        key=lambda c: (c[2] or "", c[3] or ""),
    )


def chave_de_comparacao(chave: ChaveArtefato) -> Chave:
    """(fonte, UF, competência, parte, geração): cada geração publicada é uma chave própria."""
    competencia = None if chave.competencia_arquivo is None else chave.competencia_arquivo.valor
    return (chave.fonte, chave.uf, competencia, chave.parte, chave.versao_publicacao)


def versoes_anteriores(manifesto: Path) -> dict[Chave, ArtifactVersion]:
    """Por chave de arquivo, a versão da observação obtida mais recente já no manifesto."""
    estado = Manifesto(manifesto).ler()
    anteriores: dict[Chave, ArtifactVersion] = {}
    for obs in estado.observacoes:
        versao = estado.versoes.get(obs.artifact_id or "")
        if obs.resultado is ResultadoTentativa.OBTIDO and versao is not None:
            anteriores[chave_de_comparacao(obs.chave)] = versao
    return anteriores


def carregar_leiaute_pa(config: RunConfig) -> LayoutSpec:
    caminho = Path(config.catalogos.get("leiaute_sia_pa", str(LEIAUTE_PA_PADRAO)))
    return LayoutSpec.model_validate(carregar_yaml(caminho))


_FALHAS = (ResultadoComparacao.INCONCLUSIVO, ResultadoComparacao.ARQUIVO_SUMIU)
_REVISOES = (
    ResultadoComparacao.REVISAO_REAL,
    ResultadoComparacao.CORRESPONDENCIA_AMBIGUA,
    ResultadoComparacao.BYTES_ALTERADOS_SEM_COMPARACAO,
)


@dataclass(frozen=True)
class JanelaIncompleta:
    """Família com menos competências listadas no recorte do que a janela pede."""

    fonte: str
    pedido: int
    obtido: int
    competencias: tuple[str, ...]
    motivo: str
    resultado: str | None = None


def _resultado(
    anterior: ArtifactVersion | None, nova: str | None, resultado: ResultadoComparacao, motivo: str
) -> ComparacaoVersoes:
    origem = None if anterior is None else anterior.artifact_id
    return ComparacaoVersoes(origem, nova, resultado, 0, 0, motivo)


def classificar_chave(
    anterior: ArtifactVersion | None,
    obs: ArtifactObservation,
    versoes: Mapping[str, ArtifactVersion],
    comparar: Callable[[ArtifactVersion, ArtifactVersion], ComparacaoVersoes],
) -> ComparacaoVersoes:
    """Exatamente um resultado para a chave observada nesta execução.

    Falha de obtenção é INCONCLUSIVO; sem versão anterior, ARQUIVO_NOVO; mesmo conteúdo,
    INALTERADA; família sem comparação por linhas, BYTES_ALTERADOS_SEM_COMPARACAO; senão,
    `comparar` (SIA-PA por multiconjunto).
    """
    if obs.resultado is not ResultadoTentativa.OBTIDO:
        motivo = f"observacao_sem_conteudo resultado={obs.resultado}"
        return _resultado(anterior, None, ResultadoComparacao.INCONCLUSIVO, motivo)
    nova = versoes.get(obs.artifact_id or "")
    if nova is None:
        motivo = "versao_nova_sem_registro"
        return _resultado(anterior, obs.artifact_id, ResultadoComparacao.INCONCLUSIVO, motivo)
    if anterior is None:
        motivo = "sem_versao_anterior"
        return _resultado(None, nova.artifact_id, ResultadoComparacao.ARQUIVO_NOVO, motivo)
    if anterior.artifact_id == nova.artifact_id:
        return _resultado(
            anterior, nova.artifact_id, ResultadoComparacao.INALTERADA, "mesma_versao"
        )
    if nova.chave.fonte is not FamiliaFonte.SIA_PA:
        resultado = ResultadoComparacao.BYTES_ALTERADOS_SEM_COMPARACAO
        return _resultado(
            anterior, nova.artifact_id, resultado, "familia_sem_comparacao_por_linhas"
        )
    return comparar(anterior, nova)


def sumida(anterior: ArtifactVersion) -> ComparacaoVersoes:
    return _resultado(anterior, None, ResultadoComparacao.ARQUIVO_SUMIU, "sumiu_da_listagem")


Linha = dict[str, object]


def linhas_do_relatorio(
    comparacoes: Iterable[tuple[Chave, ComparacaoVersoes]],
    janelas: Iterable[JanelaIncompleta] = (),
) -> list[Linha]:
    """Linhas de família (janela incompleta ou listagem que falhou) e uma linha por chave."""
    linhas: list[Linha] = [
        {"janela_incompleta": True, **{k: v for k, v in asdict(j).items() if v is not None}}
        for j in janelas
    ]
    linhas += [
        {
            "fonte": str(chave[0]),
            "uf": chave[1],
            "competencia": chave[2],
            "parte": chave[3],
            "versao_publicacao": chave[4],
            "anterior": c.anterior,
            "nova": c.nova,
            "resultado": str(c.resultado),
            "linhas_removidas": c.linhas_removidas,
            "linhas_adicionadas": c.linhas_adicionadas,
            "deletadas_anterior": c.deletadas_anterior,
            "deletadas_nova": c.deletadas_nova,
            "motivo": c.motivo,
        }
        for chave, c in comparacoes
    ]
    return linhas


def nao_conclusiva(linha: Linha) -> bool:
    """Janela incompleta, INCONCLUSIVO ou ARQUIVO_SUMIU: a execução sai com falha (5)."""
    return bool(linha.get("janela_incompleta")) or linha.get("resultado") in _FALHAS


def _prefixo(linhas: Sequence[Linha]) -> str:
    resultados = {linha.get("resultado") for linha in linhas} - {None}
    if any(nao_conclusiva(linha) for linha in linhas):
        return "vigilancia_inconclusiva"
    if resultados & set(_REVISOES):
        return "revisao_observada"
    if ResultadoComparacao.ARQUIVO_NOVO in resultados:
        return "arquivos_novos_observados"
    return "sem_revisao_observada" if resultados else "sem_observacao"


def resumir_linhas(linhas: Sequence[Linha], observacoes: Sequence[ArtifactObservation]) -> str:
    """Resumo calculado só das linhas gravadas, com a contagem por resultado.

    `sem_revisao_observada` só com janelas completas e todas as chaves INALTERADA;
    `sem_observacao` só sem nenhuma linha. Nunca afirma nada fora das observações.
    """
    resultados = [linha.get("resultado") for linha in linhas]
    contagens = " ".join(f"{r.value.lower()}={resultados.count(r)}" for r in ResultadoComparacao)
    janelas = sum(bool(linha.get("janela_incompleta")) for linha in linhas)
    instantes = sorted(o.observado_em for o in observacoes)
    periodo = f"de={instantes[0].isoformat()} ate={instantes[-1].isoformat()} " if instantes else ""
    return (
        f"{_prefixo(linhas)} {contagens} janelas_incompletas={janelas} "
        f"observacoes={len(observacoes)} {periodo}alcance=somente_observacoes_da_pesquisa"
    )


def resumir_vigilancia(
    observacoes: Sequence[ArtifactObservation],
    comparacoes: Sequence[ComparacaoVersoes],
) -> str:
    """Resumo de comparações avulsas (sem chave nem janela), pela mesma regra do relatório."""
    linhas: list[Linha] = [{"resultado": str(c.resultado)} for c in comparacoes]
    return resumir_linhas(linhas, observacoes)


def gravar_relatorio(caminho: Path, linhas: Sequence[Linha], resumo: str) -> None:
    """Acrescenta ao relatório as linhas da execução e o resumo."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as saida:
        for linha in [*linhas, {"resumo": resumo}]:
            saida.write(json.dumps(linha, ensure_ascii=False, sort_keys=True) + "\n")
