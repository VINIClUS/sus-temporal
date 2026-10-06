"""Passos do fluxo pela CLI sobre o mundo SINTETICO da T14, cada um com o que produziu.

Cada passo anota o código de saída do comando em `Fluxo.codigos` e guarda o que os testes
inspecionam depois. Os comandos rodam de dentro da raiz do mundo (ver `preparar_mundo`); o
código limpo e a decisão G0 são de teste, escritos só no diretório temporário.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow.parquet as pq

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.fetch import fetch_source
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.config import load_config
from sustemporal.contracts.artifacts import (
    ArtifactObservation,
    ChaveArtefato,
    FormatoArquivo,
    MotivoRequisicao,
    SourceRequest,
)
from sustemporal.contracts.base import FamiliaFonte
from sustemporal.contracts.experiment import Particao, RunResult, SplitManifest
from sustemporal.evaluation.split import SUFIXO_ENTRADAS, build_splits, carregar_spec
from sustemporal.execucoes import raiz_execucoes
from sustemporal.reporting.reproduce_etapas import (
    Derivado,
    competencias_da_particao,
    derivar_protocolo,
    janela_do_ingest,
)
from sustemporal.rules.ingest import ler_datasets
from tests.fixtures.protocolo_avaliacao import CODIGO_LIMPO, escrever_decisao
from tests.fixtures.reproducao_mundo import (
    JANELAS,
    POLITICAS,
    Mundo,
    adquirir,
    comando,
    escrever_configs,
    preparar_mundo,
    producao_do_mes,
    producao_por_competencia,
)
from tests.fixtures.sia_pa_fixtures import dbc_pa

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping

    import pytest

    from sustemporal.contracts.config import RunConfig

SPLITS = Path("config") / "splits.yaml"


@dataclass
class Fluxo:
    mundo: Mundo
    configs: Mapping[str, Path]
    codigos: dict[str, int] = field(default_factory=dict)
    ingest: Path | None = None
    execucoes: dict[tuple[str, str], RunResult] = field(default_factory=dict)
    split: SplitManifest | None = None
    freeze_id: str | None = None

    def config(self, nome: str) -> RunConfig:
        return load_config(self.configs[nome])


def iniciar(raiz: Path, mp: pytest.MonkeyPatch, *, threads: int = 1) -> Fluxo:
    """Mundo limpo, de dentro dele, com a versão de código de teste (limpa) no `freeze`.

    O diretório do mundo não é um repositório git: sem o patch, o `freeze` recusaria código sujo.
    """
    mundo = preparar_mundo(raiz)
    mp.chdir(raiz)
    mp.setattr("sustemporal.evaluation.cli.versao_codigo", lambda _: CODIGO_LIMPO)
    return Fluxo(mundo, escrever_configs(mundo, threads=threads))


def adquirir_e_ingerir(fluxo: Fluxo) -> None:
    fluxo.codigos.update({f"acquire_{n}": c for n, c in adquirir(fluxo.mundo).items()})
    configuracao = str(fluxo.configs["teste"])
    fluxo.codigos["ingest"] = comando("ingest", "--config", configuracao)
    (fluxo.ingest,) = sorted((fluxo.mundo.saidas / "ingest").iterdir())


def _runs(fluxo: Fluxo, janela: str) -> set[str]:
    raiz = raiz_execucoes(fluxo.config(janela))
    return {p.name for p in raiz.glob("val_*")} if raiz.is_dir() else set()


def _validar(fluxo: Fluxo, janela: str, politica: str, pasta: Path) -> None:
    antes = _runs(fluxo, janela)
    configuracao = str(fluxo.configs[janela])
    argumentos = [
        "validate",
        "--config",
        configuracao,
        "--policy",
        politica,
        "--ingest",
        str(pasta),
    ]
    fluxo.codigos[f"validate_{janela}_{politica}"] = comando(*argumentos)
    (novo,) = _runs(fluxo, janela) - antes
    caminho = raiz_execucoes(fluxo.config(janela)) / novo / "run_result.json"
    fluxo.execucoes[(janela, politica)] = RunResult.model_validate_json(caminho.read_text("utf-8"))


def validar_janelas(fluxo: Fluxo, janelas: tuple[str, ...] = tuple(JANELAS)) -> None:
    """`validate --ingest` das três políticas em cada janela pedida (DEV, CAL e TESTE)."""
    assert fluxo.ingest is not None
    for janela in janelas:
        competencias = JANELAS[janela]
        destino = fluxo.mundo.saidas / "janelas" / janela
        pasta = janela_do_ingest(fluxo.config(janela), fluxo.ingest, destino, competencias)
        for politica in POLITICAS:
            _validar(fluxo, janela, politica, pasta)


def linha_do_ingest(
    fluxo: Fluxo, *, processamento: str | None = None, atendimento: str, instrumento: str
) -> str:
    """`row_id` da única linha do SIA-PA com o atendimento e o instrumento pedidos."""
    assert fluxo.ingest is not None
    colunas = ["row_id", "competencia_processamento", "competencia_atendimento", "instrumento"]
    achados = [
        linha["row_id"]
        for ref in ler_datasets(fluxo.ingest)
        if ref.schema_id == "sia_pa.v1"
        for linha in pq.read_table(ref.caminho, columns=colunas).to_pylist()
        if linha["competencia_atendimento"] == atendimento
        and linha["instrumento"] == instrumento
        and processamento in (None, linha["competencia_processamento"])
    ]
    assert len(achados) == 1, achados
    return str(achados[0])


def artefatos_do_sia_pa(fluxo: Fluxo, janela: str) -> tuple[str, ...]:
    """`artifact_id` (ordenados) dos arquivos do SIA-PA que a janela (`dev`, `cal`, `teste`) lê."""
    assert fluxo.ingest is not None
    competencias = set(JANELAS[janela])
    return tuple(
        sorted(
            artefato
            for ref in ler_datasets(fluxo.ingest)
            if ref.schema_id == "sia_pa.v1" and set(competencias_da_particao(ref)) <= competencias
            for artefato in ref.artifact_ids
        )
    )


def _fontes_por_artefato(fluxo: Fluxo) -> dict[str, str]:
    """Fonte lógica de cada versão do manifesto, no formato do protocolo (entra no `split_id`)."""
    manifesto = Manifesto(fluxo.mundo.raiz / "manifestos" / NOME_MANIFESTO_AQUISICAO)
    return {
        artefato: "|".join(
            str(valor)
            for valor in (v.chave.fonte, v.chave.uf, v.chave.competencia_arquivo, v.chave.parte)
        )
        for artefato, v in manifesto.ler().versoes.items()
    }


def _com_inspecionados(
    fluxo: Fluxo, derivado: Derivado, inspecionados: Collection[str]
) -> SplitManifest:
    """O split do mesmo protocolo, mas com os artefatos inspecionados, direto no `build_splits`."""
    config = fluxo.config("teste")
    assert config.coorte is not None
    destino = fluxo.mundo.saidas / "split"
    anterior = derivado.split.split_id
    (destino / f"{anterior}.json").unlink()
    (destino / f"{anterior}{SUFIXO_ENTRADAS}").unlink()
    return build_splits(
        derivado.uniao,
        config.coorte,
        destino,
        spec=derivado.split.spec,
        fonte_por_artefato=_fontes_por_artefato(fluxo),
        inspecionados=inspecionados,
        rotulos=derivado.rotulos,
    )


def derivar(fluxo: Fluxo, *, inspecionados: Collection[str] = ()) -> SplitManifest:
    """União, rótulos e partições em `<raiz_saidas>/split`, com os insumos do TESTE ao lado.

    Os `inspecionados` entram no split direto pelo `build_splits`, sem passar pelo
    `derivar_protocolo`: o original que a reprodução refaz não depende do código que ela exerce.
    """
    assert fluxo.ingest is not None
    destino = fluxo.mundo.saidas / "split"
    config = fluxo.config("teste")
    derivado = derivar_protocolo(config, fluxo.ingest, destino, spec=carregar_spec(SPLITS))
    split = derivado.split
    if inspecionados:
        split = _com_inspecionados(fluxo, derivado, inspecionados)
    fluxo.split = split
    teste = split.hash_por_particao[Particao.TESTE]
    (destino / "insumos").mkdir(exist_ok=True)
    for (janela, _), run in fluxo.execucoes.items():
        if janela == "teste" and run.entradas[0].hash_logico == teste:
            origem = raiz_execucoes(config) / run.run_id / "entrada_validacao.json"
            shutil.copyfile(origem, destino / "insumos" / f"{run.politica_id}.json")
    return split


def congelar_e_avaliar(fluxo: Fluxo) -> None:
    """`freeze` sem G0 (recusado), com a decisão G0 de teste, `evaluate` e `annotation-export`."""
    teste, cal = str(fluxo.configs["teste"]), str(fluxo.configs["cal"])
    fluxo.codigos["freeze_sem_g0"] = comando("freeze", "--config", teste)
    escrever_decisao(Path("experiments") / "decisions", "G0", "CONTINUAR")
    fluxo.codigos["freeze"] = comando("freeze", "--config", teste)
    (manifesto,) = sorted(fluxo.mundo.congelamentos.glob("frz_*.json"))
    fluxo.freeze_id = manifesto.stem
    base = ["--config", cal, "--freeze", fluxo.freeze_id]
    fluxo.codigos["evaluate_sem_exploratory"] = comando("evaluate", *base)
    fluxo.codigos["evaluate"] = comando("evaluate", *base, "--exploratory")
    fluxo.codigos["annotation_export"] = comando("annotation-export", *base)


@dataclass(frozen=True)
class Reproducao:
    """Resultado de um `reproduce`: código de saída, destino e o `reproducao.json` lido."""

    codigo: int
    out: Path
    conteudo: dict[str, Any]
    antes: dict[str, str] = field(default_factory=dict)
    depois: dict[str, str] = field(default_factory=dict)

    @property
    def itens(self) -> dict[str, dict[str, str]]:
        return {i["item"]: i for i in self.conteudo["comparacoes"]}

    @property
    def situacoes(self) -> dict[str, str]:
        return {item: i["situacao"] for item, i in self.itens.items()}


def reproduzir(fluxo: Fluxo, config: Path, out: Path | None = None) -> Reproducao:
    """`reproduce --offline` do congelamento do fluxo; `out` padrão: `<raiz_saidas>/reproducao/`."""
    assert fluxo.freeze_id is not None
    argumentos = ["reproduce", "--config", str(config), "--freeze", fluxo.freeze_id, "--offline"]
    if out is not None:
        argumentos += ["--saida", str(out)]
    codigo = comando(*argumentos)
    destino = out or fluxo.mundo.saidas / "reproducao" / fluxo.freeze_id
    relatorio = destino / "reproducao.json"
    conteudo = json.loads(relatorio.read_text(encoding="utf-8")) if relatorio.is_file() else {}
    return Reproducao(codigo, destino, conteudo)


def instantaneo(fluxo: Fluxo) -> dict[str, str]:
    """SHA-256 de todo arquivo dos originais: dados, manifestos, saídas e congelamentos."""
    reproducao = fluxo.mundo.saidas / "reproducao"
    return {
        str(arquivo.relative_to(fluxo.mundo.raiz)): hashlib.sha256(arquivo.read_bytes()).hexdigest()
        for raiz in ("dados", "manifestos", "saidas", "congelamentos")
        for arquivo in sorted((fluxo.mundo.raiz / raiz).rglob("*"))
        if arquivo.is_file() and not arquivo.is_relative_to(reproducao)
    }


def metricas_refeitas(out: Path) -> list[dict[str, Any]]:
    """Métricas do relatório de avaliação que a reprodução refez em `out`."""
    (relatorio,) = (out / "avaliacao").rglob("rep_*.json")
    return list(json.loads(relatorio.read_text(encoding="utf-8"))["metricas"])


def _caminho_do_manifesto(fluxo: Fluxo) -> Path:
    return fluxo.mundo.raiz / "manifestos" / NOME_MANIFESTO_AQUISICAO


def chave_do_sia_pa(fluxo: Fluxo, competencia: str) -> ChaveArtefato:
    """Chave lógica do arquivo do SIA-PA da competência de arquivo pedida (o congelado)."""
    versoes = Manifesto(_caminho_do_manifesto(fluxo)).ler().versoes.values()
    (versao,) = (
        v
        for v in versoes
        if v.chave.fonte is FamiliaFonte.SIA_PA and str(v.chave.competencia_arquivo) == competencia
    )
    return versao.chave


def coletar(fluxo: Fluxo, chave: ChaveArtefato, conteudo: bytes | None) -> ArtifactObservation:
    """Coleta local (`file://`) da `chave`, registrada no manifesto de aquisição.

    Sem `conteudo` o arquivo não existe, e o manifesto registra a ausência (`NAO_ENCONTRADO`).
    """
    arquivo = fluxo.mundo.raiz / "coleta_posterior" / chave.nome_original
    arquivo.unlink(missing_ok=True)
    if conteudo is not None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(conteudo)
    pedido = SourceRequest(
        chave=chave,
        localizador=arquivo.as_uri(),
        formato_esperado=FormatoArquivo.DBC,
        tamanho_maximo_bytes=1_000_000,
        motivo=MotivoRequisicao.VIGILANCIA,
    )
    return fetch_source(pedido, fluxo.mundo.raiz / "dados", manifesto=_caminho_do_manifesto(fluxo))


@contextmanager
def coleta_depois_do_congelamento(fluxo: Fluxo) -> Iterator[list[ArtifactObservation]]:
    """Três coletas depois do `freeze` e o manifesto de aquisição como estava ao sair.

    Um arquivo novo do SIA-PA (competência 202403), a republicação de 202401 com outro conteúdo
    (uma linha repetida) e o arquivo de 202301 que sumiu do local de coleta (ausência).
    """
    teste, cal = chave_do_sia_pa(fluxo, "202401"), chave_do_sia_pa(fluxo, "202301")
    nova = ChaveArtefato(
        fonte=FamiliaFonte.SIA_PA,
        uf=teste.uf,
        competencia_arquivo="202403",
        parte=teste.parte,
        canal=teste.canal,
        nome_original="PASP2403a.dbc",
    )
    registros = producao_por_competencia()["202401"]
    caminho = _caminho_do_manifesto(fluxo)
    arquivos = [caminho, caminho.with_name(f"{caminho.name}.ancora")]
    guardados = [arquivo.read_bytes() for arquivo in arquivos]
    try:
        yield [
            coletar(fluxo, nova, dbc_pa(producao_do_mes("202403"))),
            coletar(fluxo, teste, dbc_pa([*registros, registros[0]])),
            coletar(fluxo, cal, None),
        ]
    finally:
        for arquivo, conteudo in zip(arquivos, guardados, strict=True):
            arquivo.write_bytes(conteudo)
