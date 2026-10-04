"""Comando `sustemporal ingest`: normaliza as versões do manifesto e gera a cobertura (T04).

Cada versão de conteúdo do manifesto de aquisição é despachada pela família (`ingest/registry.py`)
com os leiautes do catálogo. Quarentena, arquivo ausente e família reservada viram resultados
registrados, nunca tabela vazia; falha inesperada de uma versão vira FALHA_NORMALIZACAO e a
execução segue. Cada execução grava numa pasta nova,
`<raiz_saidas>/ingest/execucao_<instante>_<id>/`: os Parquet canônicos, `datasets.jsonl` (um
`DatasetRef` por linha, inclusive a cobertura) e `resultados.jsonl`.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

import pyarrow.parquet as pq

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.acquisition.watch import carregar_leiaute_pa
from sustemporal.contracts import EstadoIntegridade, FamiliaFonte, LayoutSpec, OrigemDados
from sustemporal.errors import ConfigInvalida, ExitCode, FalhaOperacionalErro
from sustemporal.ingest.cnes import RESERVADAS, FamiliaReservada, carregar_leiautes_cnes
from sustemporal.ingest.coverage import build_coverage
from sustemporal.ingest.dbf import ArquivoAusente, QuarentenaLeitura
from sustemporal.ingest.registry import normalizador
from sustemporal.ingest.sigtap_zip import carregar_leiautes_sigtap
from sustemporal.ingest.territorio import carregar_territorio
from sustemporal.temporal.selector import partes_esperadas_do_catalogo, uf_da_execucao

if TYPE_CHECKING:
    import argparse
    from collections.abc import Sequence

    from sustemporal.acquisition.manifest import EstadoManifesto
    from sustemporal.contracts import (
        ArtifactObservation,
        ArtifactVersion,
        ChaveArtefato,
        DatasetRef,
        RuntimeConfig,
    )
    from sustemporal.contracts.config import PilotSpec, RunConfig

__all__ = ["executar_ingest"]

logger = logging.getLogger(__name__)

# Mesmo endereçamento da aquisição (acquisition/cli.py): conteúdo em <raiz_dados>/raw.
SUBPASTA_ARMAZENAMENTO = "raw"
FONTES_NACIONAIS = frozenset({FamiliaFonte.SIGTAP})
# Mesma noção de conteúdo selecionável do seletor (temporal/selector.py, `_INTEGRAS`).
INTEGRIDADES_SELECIONAVEIS = frozenset({EstadoIntegridade.OK, EstadoIntegridade.NAO_VERIFICADO})
_NORMALIZAVEIS = frozenset(
    {FamiliaFonte.SIA_PA, FamiliaFonte.SIGTAP, FamiliaFonte.CNES_PF, FamiliaFonte.CNES_ST}
)


class _Normalizar(Protocol):
    def __call__(
        self,
        artifact: ArtifactVersion,
        layout: LayoutSpec,
        out: Path,
        *,
        runtime: RuntimeConfig | None = ...,
        origem_dados: OrigemDados = ...,
    ) -> DatasetRef: ...


def _leiautes(fonte: FamiliaFonte, config: RunConfig) -> list[LayoutSpec]:
    if fonte is FamiliaFonte.SIA_PA:
        return [carregar_leiaute_pa(config)]
    if fonte is FamiliaFonte.SIGTAP:
        return list(carregar_leiautes_sigtap().values())
    leiautes = carregar_leiautes_cnes()
    return [leiautes[fonte]] if fonte in leiautes else []


def _piloto(config: RunConfig) -> PilotSpec:
    if config.piloto is None:
        raise ConfigInvalida("ingest_exige_piloto")
    carregar_territorio(Path(config.piloto.territorio), uf=config.piloto.uf)
    return config.piloto


def _resultado(
    versao: ArtifactVersion, layout_id: str | None, estado: str, **extras: str | None
) -> dict[str, str | None]:
    return {
        "artifact_id": versao.artifact_id,
        "fonte": versao.chave.fonte.value,
        "leiaute": layout_id,
        "estado": estado,
        **extras,
    }


class _Execucao:
    def __init__(self, config: RunConfig, saida: Path) -> None:
        raiz = Path(config.runtime.raiz_dados) / SUBPASTA_ARMAZENAMENTO
        self.runtime = config.runtime.model_copy(update={"raiz_dados": str(raiz)})
        self.config = config
        self.origem = config.origem_dados or OrigemDados.SINTETICO
        self.saida = saida
        self.datasets: list[DatasetRef] = []
        self.resultados: list[dict[str, str | None]] = []
        self.sia_pa_incompleto: dict[str, str] = {}
        self.falhas: dict[str, str] = {}
        self.fora_do_corte: set[tuple[str, str | None]] = set()

    def normalizar(self, versao: ArtifactVersion) -> None:
        fonte = versao.chave.fonte
        if fonte in RESERVADAS:
            motivo = f"familia_reservada familia={RESERVADAS[fonte]}"
            self.resultados.append(_resultado(versao, None, "FAMILIA_RESERVADA", motivo=motivo))
            return
        funcao = cast("_Normalizar", normalizador(fonte))
        for layout in _leiautes(fonte, self.config):
            self._uma(funcao, versao, layout)

    def admitir(
        self, versao: ArtifactVersion, recorte: _Recorte, instantes: list[datetime]
    ) -> bool:
        detalhe = recorte.fora(versao.chave)
        if detalhe is not None:
            self.resultados.append(_resultado(versao, None, "FORA_DO_RECORTE", **detalhe))
            return False
        if any(recorte.no_corte(instante) for instante in instantes):
            return True
        primeira = min(instantes).isoformat() if instantes else None
        self.resultados.append(
            _resultado(versao, None, "FORA_DO_CORTE", primeira_observacao=primeira)
        )
        competencia = versao.chave.competencia_arquivo
        if versao.chave.fonte is FamiliaFonte.SIA_PA and competencia is not None:
            self.fora_do_corte.add((competencia.valor, versao.chave.parte))
        return False

    def propagar_incompletude(self, versoes: Sequence[ArtifactVersion]) -> None:
        """Competência de arquivo incompleta contamina as competências de processamento que
        seus conjuntos trazem (PA_MVM pode diferir do nome do arquivo)."""
        por_artefato = {v.artifact_id: v.chave.competencia_arquivo for v in versoes}
        herdadas: dict[str, str] = {}
        for dataset in self.datasets:
            if dataset.schema_id != "sia_pa.v1":
                continue
            arquivos = {por_artefato.get(a) for a in dataset.artifact_ids} - {None}
            origem = next(
                (c.valor for c in arquivos if c is not None and c.valor in self.sia_pa_incompleto),
                None,
            )
            if origem is None:
                continue
            for valor in _competencias_processamento(dataset):
                if valor not in self.sia_pa_incompleto:
                    herdadas[valor] = f"incompleto_via_arquivo competencia_arquivo={origem}"
        self.sia_pa_incompleto.update(herdadas)

    def marcar_tentativas_sem_versao(
        self, versoes: Sequence[ArtifactVersion], observacoes: Sequence[ArtifactObservation]
    ) -> None:
        """Parte do SIA-PA tentada e nunca obtida torna a competência incompleta."""
        obtidas = {_chave_logica(v.chave) for v in versoes}
        for observacao in observacoes:
            chave = observacao.chave
            competencia = chave.competencia_arquivo
            sem_versao = _chave_logica(chave) not in obtidas
            if chave.fonte is FamiliaFonte.SIA_PA and competencia is not None and sem_versao:
                self.sia_pa_incompleto[competencia.valor] = observacao.resultado.value

    def marcar_partes(self, versoes: Sequence[ArtifactVersion], config: RunConfig) -> None:
        """Completude das partes do SIA-PA com a mesma semântica do seletor (T06), contando só
        versões íntegras selecionáveis: parte vista sem versão íntegra (em quarentena ou fora do
        corte), versão íntegra que não normalizou, republicação divergente, parte declarada sem
        versão, parte não declarada ou partes sem declaração no catálogo tornam a competência
        incompleta (a aquisição não grava observação de parte ausente da listagem)."""
        esperadas_por = partes_esperadas_do_catalogo(config)
        vistas: dict[str, set[str | None]] = defaultdict(set)
        for valor, parte in self.fora_do_corte:
            vistas[valor].add(parte)
        integras: dict[str, dict[str | None, set[str]]] = defaultdict(lambda: defaultdict(set))
        for versao in versoes:
            competencia = versao.chave.competencia_arquivo
            if versao.chave.fonte is not FamiliaFonte.SIA_PA or competencia is None:
                continue
            vistas[competencia.valor].add(versao.chave.parte)
            if versao.integridade in INTEGRIDADES_SELECIONAVEIS:
                integras[competencia.valor][versao.chave.parte].add(versao.artifact_id)
        for valor, partes in vistas.items():
            por_parte = integras[valor]
            motivo = (
                _republicacao(por_parte)
                or _sem_integra(partes, por_parte)
                or self._falha_integra(por_parte)
                or _incompletude(set(por_parte), esperadas_por.get((FamiliaFonte.SIA_PA, valor)))
            )
            if motivo is not None:
                self.sia_pa_incompleto[valor] = motivo

    def _falha_integra(self, por_parte: dict[str | None, set[str]]) -> str | None:
        ids = sorted(i for conjunto in por_parte.values() for i in conjunto if i in self.falhas)
        return self.falhas[ids[0]] if ids else None

    def _uma(self, funcao: _Normalizar, versao: ArtifactVersion, layout: LayoutSpec) -> None:
        try:
            dataset = funcao(
                versao, layout, self.saida, runtime=self.runtime, origem_dados=self.origem
            )
        except QuarentenaLeitura as erro:
            estado, motivo = erro.estado.value, erro.motivo
        except (ArquivoAusente, FamiliaReservada) as erro:
            estado, motivo = type(erro).__name__.upper(), str(erro)
        except (FalhaOperacionalErro, ValueError) as erro:
            estado, motivo = "FALHA_NORMALIZACAO", f"{type(erro).__name__} {erro}"[:300]
        else:
            self.datasets.append(dataset)
            resultado = _resultado(versao, layout.layout_id, "NORMALIZADO")
            resultado["dataset_id"] = dataset.dataset_id
            self.resultados.append({**resultado, **_diagnostico(versao, dataset)})
            return
        logger.warning("ingest_sem_tabela id=%s estado=%s", versao.artifact_id, estado)
        self.resultados.append(_resultado(versao, layout.layout_id, estado, motivo=motivo))
        self.falhas[versao.artifact_id] = estado


def _diagnostico(versao: ArtifactVersion, dataset: DatasetRef) -> dict[str, str]:
    """Linhas do SIA-PA (não deletadas) com PA_MVM diferente da competência do arquivo;
    o dado fica preservado, só é contado."""
    competencia = versao.chave.competencia_arquivo
    if dataset.schema_id != "sia_pa.v1" or competencia is None:
        return {}
    colunas = ["competencia_processamento", "deletado"]
    linhas = pq.read_table(dataset.caminho, columns=colunas).to_pylist()
    divergentes = sum(
        1
        for linha in linhas
        if not linha["deletado"] and linha["competencia_processamento"] != competencia.valor
    )
    if not divergentes:
        return {}
    return {"diagnostico": f"competencia_processamento_divergente_do_arquivo n={divergentes}"}


def _competencias_processamento(dataset: DatasetRef) -> set[str]:
    colunas = ["competencia_processamento", "deletado"]
    tabela = pq.read_table(dataset.caminho, columns=colunas)
    return {
        str(linha["competencia_processamento"])
        for linha in tabela.to_pylist()
        if linha["competencia_processamento"] is not None and not linha["deletado"]
    }


def _republicacao(por_parte: dict[str | None, set[str]]) -> str | None:
    """Mais de uma versão de conteúdo para a mesma parte: o seletor dá AMBIGUA."""
    divergentes = sorted(parte or "" for parte, ids in por_parte.items() if len(ids) > 1)
    if not divergentes:
        return None
    return f"republicacao_com_conteudo_divergente partes={','.join(divergentes)}"


def _sem_integra(vistas: set[str | None], por_parte: dict[str | None, set[str]]) -> str | None:
    """Parte vista só em quarentena ou fora do corte: o seletor não tem o que selecionar."""
    sem = sorted(parte or "" for parte in vistas if not por_parte.get(parte))
    if not sem:
        return None
    return f"parte_sem_versao_integra_selecionavel partes={','.join(sem)}"


def _incompletude(obtidas: set[str | None], esperadas: frozenset[str] | None) -> str | None:
    nomeadas = {parte for parte in obtidas if parte is not None}
    if esperadas is None:
        if not nomeadas:
            return None
        return f"partes_sem_declaracao completude=INDETERMINADA partes={','.join(sorted(nomeadas))}"
    extras = nomeadas - esperadas
    if extras:
        return f"partes_nao_declaradas extras={','.join(sorted(extras))}"
    faltantes = esperadas - nomeadas
    if faltantes:
        return f"partes_ausentes ausentes={','.join(sorted(faltantes))}"
    return None


@dataclass(frozen=True)
class _Recorte:
    """Recorte da execução: famílias configuradas, UF (família nacional fica) e corte."""

    familias: frozenset[FamiliaFonte]
    uf: str | None
    corte: datetime | None

    def fora(self, chave: ChaveArtefato) -> dict[str, str] | None:
        """Detalhe do motivo quando a chave fica fora; None quando entra."""
        if chave.fonte not in self.familias:
            return {"motivo": "familia_nao_configurada", "familia": chave.fonte.value}
        if chave.fonte in FONTES_NACIONAIS:
            return (
                None if chave.uf is None else {"motivo": "uf_em_familia_nacional", "uf": chave.uf}
            )
        if chave.uf is None:
            return {"motivo": "uf_ausente_em_familia_regional"}
        return None if chave.uf == self.uf else {"uf": chave.uf}

    def no_corte(self, instante: datetime) -> bool:
        return self.corte is None or instante <= self.corte


def _recortar(
    manifesto: EstadoManifesto, recorte: _Recorte, execucao: _Execucao
) -> tuple[list[ArtifactVersion], list[ArtifactObservation], int]:
    """Arquivos publicados no recorte e no corte; os de fora viram resultado, nunca somem."""
    publicadas = [v for v in manifesto.versoes.values() if v.chave.tipo_conteudo is None]
    observadas: dict[str, list[datetime]] = defaultdict(list)
    for observacao in manifesto.observacoes:
        if observacao.artifact_id is not None:
            observadas[observacao.artifact_id].append(observacao.observado_em)
    versoes = [v for v in publicadas if execucao.admitir(v, recorte, observadas[v.artifact_id])]
    observacoes = [
        o
        for o in manifesto.observacoes
        if o.chave.tipo_conteudo is None
        and recorte.fora(o.chave) is None
        and recorte.no_corte(o.observado_em)
    ]
    return versoes, observacoes, len(manifesto.versoes) - len(publicadas)


def _chave_logica(chave: ChaveArtefato) -> tuple[object, ...]:
    return (chave.fonte, chave.uf, chave.competencia_arquivo, chave.parte)


def _pasta_execucao(raiz: Path) -> Path:
    """Pasta nova por execução (instante UTC + sufixo aleatório); nunca sobrescreve outra."""
    pasta = raiz / f"execucao_{datetime.now(UTC):%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex[:8]}"
    pasta.mkdir(parents=True, exist_ok=False)
    return pasta


def _gravar_jsonl(destino: Path, linhas: list[str]) -> None:
    temporario = destino.with_name(f".{destino.name}.tmp")
    temporario.write_text("".join(f"{linha}\n" for linha in linhas), encoding="utf-8")
    temporario.replace(destino)


def executar_ingest(args: argparse.Namespace, config: RunConfig) -> int:
    """Normaliza cada versão do manifesto de aquisição pela família e grava a cobertura.

    Raises:
        ConfigInvalida: configuração sem piloto ou com território inválido.
    """
    piloto = _piloto(config)
    saida = _pasta_execucao(Path(config.runtime.raiz_saidas) / "ingest")
    execucao = _Execucao(config, saida)
    manifesto = Manifesto(Path(config.runtime.raiz_manifestos) / NOME_MANIFESTO_AQUISICAO).ler()
    recorte = _Recorte(
        frozenset(piloto.familias_fontes), uf_da_execucao(config), config.corte_observacao
    )
    versoes, observacoes, listagens = _recortar(manifesto, recorte, execucao)
    for versao in versoes:
        if versao.chave.fonte in {*RESERVADAS, *_NORMALIZAVEIS}:
            execucao.normalizar(versao)
    execucao.marcar_tentativas_sem_versao(versoes, observacoes)
    execucao.marcar_partes(versoes, config)
    execucao.propagar_incompletude(versoes)
    competencias = [c.valor for c in piloto.competencias_processamento]
    sia_pa = [d for d in execucao.datasets if d.schema_id == "sia_pa.v1"]
    auxiliares = [d for d in execucao.datasets if d.schema_id != "sia_pa.v1"]
    cobertura = build_coverage(
        sia_pa,
        auxiliares,
        competencias,
        saida,
        runtime=execucao.runtime,
        origem_dados=execucao.origem,
        sia_pa_incompleto=execucao.sia_pa_incompleto,
    )
    datasets = [*execucao.datasets, cobertura]
    _gravar_jsonl(saida / "datasets.jsonl", [d.model_dump_json() for d in datasets])
    _gravar_jsonl(saida / "resultados.jsonl", [json.dumps(r) for r in execucao.resultados])
    logger.info(
        "ingest_concluido versoes=%s datasets=%s listagens_ignoradas=%s args=%s",
        len(manifesto.versoes),
        len(datasets),
        listagens,
        vars(args).get("comando"),
    )
    return ExitCode.OK
