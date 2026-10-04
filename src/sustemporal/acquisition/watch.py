"""Observação de republicações em janela móvel (T13).

Cada execução observa de novo os arquivos da janela, inclusive sem mudança: toda tentativa vira
observação no manifesto. A comparação com a versão observada antes é por multiconjunto de linhas
(`acquisition.comparacao`). A cadência (semanal) é do agendador externo.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sustemporal.acquisition.comparacao import ComparacaoVersoes, ResultadoComparacao
from sustemporal.acquisition.fetch import agora_utc, fetch_source
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts import LayoutSpec
from sustemporal.contracts.artifacts import ResultadoTentativa
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
    "carregar_leiaute_pa",
    "chave_de_comparacao",
    "chaves_sumidas",
    "competencias_da_janela",
    "gravar_relatorio",
    "observe_updates",
    "resumir_vigilancia",
    "versoes_anteriores",
]

logger = logging.getLogger(__name__)

LEIAUTE_PA_PADRAO = Path(__file__).resolve().parents[3] / "catalog" / "layouts" / "sia_pa.yaml"
NOME_RELATORIO = "vigilancia.jsonl"
_MESES_PROCURADOS = 120
RECORTE_INICIO = CompetenciaArquivo("201801")
RECORTE_FIM = CompetenciaArquivo("202512")

Chave = tuple[object, str | None, str | None, str | None]


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
    janela porque chegaram competências novas, não porque sumiram.
    """
    inicio = janela[0].valor if janela else RECORTE_INICIO.valor
    return sorted(
        (c for c in anteriores if c[0] is fonte and c not in atuais and (c[2] or "") >= inicio),
        key=lambda c: (c[2] or "", c[3] or ""),
    )


def chave_de_comparacao(chave: ChaveArtefato) -> Chave:
    competencia = chave.competencia_arquivo
    return (chave.fonte, chave.uf, None if competencia is None else competencia.valor, chave.parte)


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


def resumir_vigilancia(
    observacoes: Sequence[ArtifactObservation], comparacoes: Sequence[ComparacaoVersoes]
) -> str:
    """Resumo que só fala do que a pesquisa observou, sem afirmar nada fora das observações."""
    resultados = [c.resultado for c in comparacoes]
    inconclusivas = resultados.count(ResultadoComparacao.INCONCLUSIVO)
    revisoes = len(resultados) - inconclusivas - resultados.count(ResultadoComparacao.INALTERADA)
    instantes = sorted(o.observado_em for o in observacoes)
    if not instantes:
        return "sem_observacao alcance=somente_observacoes_da_pesquisa"
    prefixo = "revisao_observada" if revisoes else "sem_revisao_observada"
    if not revisoes and inconclusivas:
        prefixo = "vigilancia_inconclusiva"
    return (
        f"{prefixo} revisoes={revisoes} inconclusivas={inconclusivas} "
        f"observacoes={len(observacoes)} "
        f"de={instantes[0].isoformat()} ate={instantes[-1].isoformat()} "
        "alcance=somente_observacoes_da_pesquisa"
    )


def gravar_relatorio(
    caminho: Path,
    comparacoes: Iterable[tuple[Chave, ComparacaoVersoes]],
    resumo: str,
) -> None:
    """Acrescenta ao relatório uma linha por comparação e uma linha de resumo."""
    linhas = [
        {
            "fonte": str(chave[0]),
            "uf": chave[1],
            "competencia": chave[2],
            "parte": chave[3],
            "anterior": c.anterior,
            "nova": c.nova,
            "resultado": str(c.resultado),
            "linhas_removidas": c.linhas_removidas,
            "linhas_adicionadas": c.linhas_adicionadas,
            "mudancas_de_delecao": c.mudancas_de_delecao,
            "motivo": c.motivo,
        }
        for chave, c in comparacoes
    ]
    linhas.append({"resumo": resumo})
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("a", encoding="utf-8") as saida:
        for linha in linhas:
            saida.write(json.dumps(linha, ensure_ascii=False, sort_keys=True) + "\n")
