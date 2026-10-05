"""Cenário confirmatório SINTETICO, rotulado REAL só para exercitar os portões (T11).

Nada aqui é dado real nem decisão humana: o rótulo REAL só satisfaz os contratos do modo
confirmatório, e as decisões G0/G2 são escritas em diretórios temporários dos testes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig
from sustemporal.contracts.experiment import (
    ModoExecucao,
    Particao,
    SplitManifest,
    TipoExecucao,
)
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id
from sustemporal.contracts.temporal import MetodoId, SnapshotSet
from sustemporal.evaluation.features import FEATURES_PADRAO
from sustemporal.evaluation.freeze import Protocolo, congelar
from sustemporal.evaluation.freeze_conferencia import EstadoAtual
from sustemporal.evaluation.metrics import ReferenciaCongelamento
from sustemporal.evaluation.split import SUFIXO_ENTRADAS
from sustemporal.rules.catalog import carregar_regras, catalogo_sha256
from sustemporal.rules.entrada import EntradaValidacao
from sustemporal.runtime_info import ambiente
from sustemporal.temporal.politicas import carregar_politica
from tests.fixtures.protocolo_avaliacao import (
    CODIGO_LIMPO,
    escrever_decisao,
    relogio,
    run_agregados,
)
from tests.fixtures.protocolo_dados import (
    PROC_REJEITADO,
    LinhaPa,
    artefato,
    gravar_rotulos,
    gravar_sia_pa,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sustemporal.contracts import Ambiente, FreezeManifest, RunResult
    from sustemporal.contracts.temporal import PoliticaTemporal
    from tests.fixtures.protocolo_dados import Cenario

CATALOGO_SIA_PA = Path(__file__).resolve().parents[2] / "catalog" / "schemas" / "sia_pa.yaml"
CONFIG_PROTOCOLO: dict[str, Any] = {
    "versao": "1",
    "origem_dados": "REAL",
    "bootstrap": {"correcao": "HOLM", "reamostragens": 50},
    "catalogos": {"esquema_sia_pa": str(CATALOGO_SIA_PA)},
}
POLITICA_DO_METODO = {
    MetodoId.M_TEMP: "M_TEMP_PADRAO",
    MetodoId.B_ATEND: "B_ATEND",
    MetodoId.B_PROC: "B_PROC",
}
POLITICAS_DO_PROTOCOLO = tuple(POLITICA_DO_METODO.values())
ESQUEMA_CNES = "cnes_estabelecimento.v1"
ESQUEMA_SIGTAP = "sigtap_procedimento.v1"
ESQUEMA_COBERTURA = "cobertura.v1"
ESQUEMA_SELECAO = "selecao_versoes.v1"
ESQUEMAS_DA_POPULACAO = frozenset({"sia_pa.v1", "sia_pa_rotulos.v1"})
COMPETENCIA_DO_TESTE = "202401"
OUTRO_SHA = "f" * 64
MUTACOES_DO_AMBIENTE: dict[str, Callable[[Ambiente], Ambiente]] = {
    "python": lambda a: a.model_copy(update={"python": "0.0.0"}),
    "pacotes": lambda a: a.model_copy(update={"pacotes": {**a.pacotes, "duckdb": "0.0.0"}}),
    "uv_lock_sha256": lambda a: a.model_copy(update={"uv_lock_sha256": OUTRO_SHA}),
}


def como_real(ref: DatasetRef) -> DatasetRef:
    return ref.model_copy(update={"origem_dados": OrigemDados.REAL})


def auxiliar_fora_do_manifesto() -> DatasetRef:
    """Conjunto auxiliar (outro esquema), que o manifesto não congela e a conferência ignora."""
    esquema, conteudo = "sigtap_procedimento.v1", f"lh1:{'d' * 64}"
    return DatasetRef(
        dataset_id=calcular_dataset_id(esquema, conteudo, ()),
        schema_id=esquema,
        caminho="auxiliar_sintetico.parquet",
        hash_logico=conteudo,
        linhas=0,
        artifact_ids=(),
        origem_dados=OrigemDados.REAL,
        produzido_por="tests.fixtures.protocolo_confirmatorio",
    )


def conjunto_sintetico(esquema: str, versao: str) -> DatasetRef:
    """Conjunto não populacional REAL sem arquivo: só a identidade importa na conferência."""
    conteudo = f"lh1:{hashlib.sha256(f'{esquema}:{versao}'.encode()).hexdigest()}"
    return DatasetRef(
        dataset_id=calcular_dataset_id(esquema, conteudo, ()),
        schema_id=esquema,
        caminho=f"{esquema}.{versao}.parquet",
        hash_logico=conteudo,
        linhas=0,
        artifact_ids=(),
        origem_dados=OrigemDados.REAL,
        produzido_por="tests.fixtures.protocolo_confirmatorio",
    )


def snapshots_sinteticos(versao: str) -> SnapshotSet:
    """`SnapshotSet` vazio que só se distingue pelo hash de dataset da `versao`."""
    return SnapshotSet.criar(
        artifact_ids=(),
        observation_ids=(),
        dataset_hashes=(conjunto_sintetico(ESQUEMA_SELECAO, versao).hash_logico,),
        selecoes=(),
    )


def entrada_da_politica(
    cenario: Cenario, politica_id: str, *, sigtap: str = "2024-01", cobertura: str = "base"
) -> EntradaValidacao:
    """Entrada de validação sobre o TESTE; a seleção e os snapshots dependem da política."""
    assert cenario.split.particoes is not None
    return EntradaValidacao(
        dataset=como_real(cenario.split.particoes[Particao.TESTE]),
        snapshots=snapshots_sinteticos(politica_id),
        auxiliares=(
            conjunto_sintetico(ESQUEMA_CNES, "2024-01"),
            conjunto_sintetico(ESQUEMA_SIGTAP, sigtap),
        ),
        selecoes=conjunto_sintetico(ESQUEMA_SELECAO, politica_id),
        cobertura=conjunto_sintetico(ESQUEMA_COBERTURA, cobertura),
    )


def insumos_do_teste(cenario: Cenario) -> dict[str, EntradaValidacao]:
    """Uma entrada de validação por política do protocolo (M_TEMP, B_ATEND e B_PROC)."""
    return {politica: entrada_da_politica(cenario, politica) for politica in POLITICAS_DO_PROTOCOLO}


def entradas_nao_populacionais(run: RunResult) -> tuple[DatasetRef, ...]:
    """Entradas da execução que não são a população nem os rótulos (auxiliares, seleção, ...)."""
    return tuple(d for d in run.entradas if d.schema_id not in ESQUEMAS_DA_POPULACAO)


def com_conjunto_trocado(run: RunResult, esquema: str, novo: DatasetRef) -> RunResult:
    """Mesma execução com a entrada do `esquema` trocada por `novo` (outra versão do conjunto)."""
    entradas = tuple(novo if d.schema_id == esquema else d for d in run.entradas)
    assert entradas != run.entradas
    return run.model_copy(update={"entradas": entradas})


def politicas_do_catalogo() -> list[PoliticaTemporal]:
    return [carregar_politica(politica_id) for politica_id in POLITICA_DO_METODO.values()]


def config_confirmatoria(freeze_id: str, **campos: Any) -> RunConfig:
    dados = {**CONFIG_PROTOCOLO, "modo": "CONFIRMATORIO", "freeze_id": freeze_id, **campos}
    return RunConfig.model_validate(dados)


@dataclass(frozen=True)
class Confirmatorio:
    """Congelamento, G2, config confirmatória, estado atual e execuções compatíveis (TESTE)."""

    cenario: Cenario
    manifesto: FreezeManifest
    config: RunConfig
    estado: EstadoAtual
    decisoes: Path
    g2: str
    runs: list[RunResult]
    rotulos: DatasetRef

    def referencia(self, **trocas: Any) -> ReferenciaCongelamento:
        campos: dict[str, Any] = {
            "freeze_id": self.manifesto.freeze_id,
            "decisao_g2": self.g2,
            "decisoes": self.decisoes,
            "manifesto": self.manifesto,
            "estado": self.estado,
        }
        return ReferenciaCongelamento(**{**campos, **trocas})

    def estado_com(self, **trocas: Any) -> EstadoAtual:
        """O estado atual com os campos trocados (config, ambiente, regras, ...)."""
        return replace(self.estado, **trocas)


def resultados_do_teste(cenario: Cenario, metodo: MetodoId) -> dict[str, str]:
    """Resultado do método para cada registro da partição TESTE (cobertura completa)."""
    teste = [lp for lp in cenario.linhas if lp.competencia_processamento == COMPETENCIA_DO_TESTE]
    if metodo is MetodoId.M_TEMP:
        return {
            lp.row_id: "ALERTA" if lp.procedimento == PROC_REJEITADO else "SEM_VIOLACAO_VERIFICADA"
            for lp in teste
        }
    if metodo is MetodoId.B_PROC:
        return {lp.row_id: "ALERTA" if i < 5 else "ABSTENCAO" for i, lp in enumerate(teste)}
    resultado = "SEM_VIOLACAO_VERIFICADA" if metodo is MetodoId.B_ATEND else "SEM_ALERTA"
    return {lp.row_id: resultado for lp in teste}


def run_compativel(
    cenario: Cenario,
    manifesto: FreezeManifest,
    config: RunConfig,
    out: Path,
    metodo: MetodoId,
    *,
    uniforme: str | None = None,
    resultados: dict[str, str] | None = None,
    entradas_a_mais: tuple[DatasetRef, ...] = (),
    repetidas: tuple[str, ...] = (),
) -> RunResult:
    """Execução do método sobre o TESTE, igual ao protocolo congelado.

    `uniforme` dá o mesmo resultado a todas as linhas (uma execução corrigida, com outro id);
    `resultados` troca o que a saída traz (linhas a menos ou a mais), `entradas_a_mais` declara
    outras entradas congeladas, como as partições que um baseline também lê, e `repetidas` grava
    esses `row_id` duas vezes.
    """
    assert cenario.split.particoes is not None
    if resultados is None:
        resultados = resultados_do_teste(cenario, metodo)
    if uniforme is not None:
        resultados = dict.fromkeys(resultados, uniforme)
    teste = como_real(cenario.split.particoes[Particao.TESTE])
    comuns: dict[str, Any] = {
        "origem": OrigemDados.REAL,
        "modo": ModoExecucao.CONFIRMATORIO,
        "freeze_id": manifesto.freeze_id,
        "config_hash": config.config_hash,
        "codigo": CODIGO_LIMPO,
        "ambiente": manifesto.ambiente,
    }
    if metodo is MetodoId.B_ML:
        entradas = (teste, auxiliar_fora_do_manifesto(), *entradas_a_mais)
        return run_agregados(
            metodo,
            resultados,
            out,
            tipo=TipoExecucao.BASELINE_ML,
            repetidas=repetidas,
            entradas=entradas,
            **comuns,
        )
    politica_id = POLITICA_DO_METODO[metodo]
    insumos = entrada_da_politica(cenario, politica_id)
    entradas = (teste, *insumos.auxiliares, insumos.selecoes, insumos.cobertura, *entradas_a_mais)
    return run_agregados(
        metodo,
        resultados,
        out,
        repetidas=repetidas,
        politica_id=politica_id,
        catalogo_regras_sha256=catalogo_sha256(carregar_regras()),
        snapshot_set_id=insumos.snapshots.snapshot_id,
        entradas=entradas,
        **comuns,
    )


def runs_compativeis(
    cenario: Cenario, manifesto: FreezeManifest, config: RunConfig, out: Path
) -> list[RunResult]:
    """Três execuções de validação e uma de baseline, todas iguais ao protocolo congelado."""
    metodos = (*POLITICA_DO_METODO, MetodoId.B_ML)
    return [run_compativel(cenario, manifesto, config, out, metodo) for metodo in metodos]


def montar_confirmatorio(
    raiz: Path, cenario: Cenario, *, catalogo: Path = CATALOGO_SIA_PA, **protocolo: Any
) -> Confirmatorio:
    """Congela o protocolo (G0), abre o TESTE (G2) e gera as execuções compatíveis.

    `catalogo` é o arquivo de catálogo da config e do congelamento (uma cópia nos testes que o
    alteram); o estado atual espelha o que foi congelado.
    """
    assert cenario.split.rotulos_por_particao is not None
    decisoes = raiz / "decisoes"
    escrever_decisao(decisoes, "G0", "CONTINUAR")
    catalogos = {"esquema_sia_pa": str(catalogo)}
    campos: dict[str, Any] = {
        "config": RunConfig.model_validate({**CONFIG_PROTOCOLO, "catalogos": catalogos}),
        "split": cenario.split,
        "features": FEATURES_PADRAO,
        "dataset": cenario.dataset,
        "rotulos": cenario.rotulos,
        "catalogos": {nome: Path(caminho) for nome, caminho in catalogos.items()},
        "regras": carregar_regras(),
        "politicas": politicas_do_catalogo(),
        "insumos": insumos_do_teste(cenario),
        **protocolo,
    }
    manifesto = congelar(
        Protocolo(**campos),
        raiz / "frozen",
        decisoes=decisoes,
        codigo=CODIGO_LIMPO,
        relogio=relogio,
    )
    g2 = escrever_decisao(decisoes, "G2", "ABRIR_TESTE", freeze_id=manifesto.freeze_id)
    config = config_confirmatoria(manifesto.freeze_id, catalogos=catalogos)
    estado = EstadoAtual(
        config=config,
        split=campos["split"],
        features=campos["features"],
        datasets=[campos["dataset"], campos["rotulos"]],
        codigo=CODIGO_LIMPO,
        ambiente=ambiente(Path.cwd()),
        regras=campos["regras"],
        politicas=campos["politicas"],
    )
    return Confirmatorio(
        cenario=cenario,
        manifesto=manifesto,
        config=config,
        estado=estado,
        decisoes=decisoes,
        g2=f"experiments/decisions/{g2.name}",
        runs=runs_compativeis(cenario, manifesto, config, raiz / "runs"),
        rotulos=como_real(cenario.split.rotulos_por_particao[Particao.TESTE]),
    )


def sia_pa_desconhecido(raiz: Path) -> DatasetRef:
    """Registro `sia_pa.v1` que o congelamento não conhece."""
    estranha = LinhaPa(artefato("pa_estranha"), 0, competencia_processamento="202401")
    return como_real(gravar_sia_pa([estranha], raiz / "estranha.parquet"))


def split_como_real(split: SplitManifest) -> SplitManifest:
    """Mesmo split com população e rótulos marcados REAL (rótulo de teste, conteúdo igual)."""
    assert split.particoes is not None
    assert split.rotulos_por_particao is not None
    reais = {
        "particoes": {p: como_real(r) for p, r in split.particoes.items()},
        "rotulos_por_particao": {p: como_real(r) for p, r in split.rotulos_por_particao.items()},
    }
    return split.model_copy(update=reais)


def reescrever_split_como_real(pasta: Path) -> None:
    """Marca como REAL, no disco, o split e as entradas que a CLI lê (rótulo de teste)."""
    for caminho in sorted(pasta.glob("spl_*.json")):
        if caminho.name.endswith(SUFIXO_ENTRADAS):
            entradas = json.loads(caminho.read_text(encoding="utf-8"))
            for chave in ("dataset", "rotulos"):
                entradas[chave]["origem_dados"] = "REAL"
            caminho.write_text(json.dumps(entradas, indent=2), encoding="utf-8")
            continue
        split = SplitManifest.model_validate_json(caminho.read_text(encoding="utf-8"))
        texto = split_como_real(split).model_dump_json(indent=2)
        caminho.write_text(texto, encoding="utf-8")


def rotulos_do_teste_invertidos(cenario: Cenario, destino: Path) -> DatasetRef:
    """Arquivo REAL de rótulos do TESTE com as classes binárias trocadas, ainda válido."""
    inverso = {"NAO_APROVADO": "APROVADO_TOTAL", "APROVADO_TOTAL": "NAO_APROVADO"}
    teste = [lp for lp in cenario.linhas if lp.competencia_processamento == COMPETENCIA_DO_TESTE]
    rotulos = {lp.row_id: cenario.rotulo_por_row[lp.row_id] for lp in teste}
    trocados = {row_id: inverso.get(rotulo, rotulo) for row_id, rotulo in rotulos.items()}
    return gravar_rotulos(trocados, destino, origem=OrigemDados.REAL)


def split_com_rotulos_do_teste(split: SplitManifest, rotulos: DatasetRef) -> SplitManifest:
    """Mesmo `split_id` e outro rótulo para o TESTE: o id não deriva do conteúdo do manifesto."""
    dados = split.model_dump(mode="json")
    dados["rotulos_por_particao"][Particao.TESTE.value] = rotulos.model_dump(mode="json")
    return SplitManifest.model_validate(dados)


def editar_rotulos_do_teste_no_disco(pasta: Path, cenario: Cenario, destino: Path) -> SplitManifest:
    """Reescreve o split do disco com os rótulos do TESTE trocados, mantendo o `split_id`."""
    (caminho,) = [c for c in pasta.glob("spl_*.json") if not c.name.endswith(SUFIXO_ENTRADAS)]
    lido = SplitManifest.model_validate_json(caminho.read_text(encoding="utf-8"))
    editado = split_com_rotulos_do_teste(lido, rotulos_do_teste_invertidos(cenario, destino))
    caminho.write_text(editado.model_dump_json(indent=2), encoding="utf-8")
    return editado
