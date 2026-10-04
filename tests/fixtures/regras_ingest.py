"""Pasta de `sustemporal ingest` e manifesto de aquisição SINTETICOS para `validate --ingest`.

Produção SIA-PA de 202302 em duas partes (a e b) com uma linha física repetida entre elas e uma
linha de município fora do território. CNES e SIGTAP de 202301 e 202302; o par
(1234567, 225125) existe no CNES de janeiro e falta no de fevereiro. Códigos IBGE sintéticos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts.artifacts import ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte, OrigemDados
from sustemporal.contracts.records import TipoCanonico
from sustemporal.ingest.coverage import build_coverage
from sustemporal.rules.catalog import carregar_esquema
from tests.fixtures.regras_cenario import gravar_dataset, reemitir
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion
    from sustemporal.contracts.records import DatasetRef

__all__ = [
    "MUNICIPIOS",
    "MUNICIPIO_FORA",
    "MundoIngest",
    "gravar_territorio",
    "montar_ingest",
]

JANEIRO, FEVEREIRO = "202301", "202302"
_PROCEDIMENTO, _CBO, _CNES = "0301010072", "225125", "1234567"
_PARTES = ("a", "b")
MUNICIPIOS = ("350010", "350020")
MUNICIPIO_FORA = "359990"
_Item = tuple["ArtifactObservation", "ArtifactVersion | None"]


@dataclass(frozen=True)
class MundoIngest:
    pasta: Path
    config: Path
    manifesto: Path
    saida: Path


def _digito(ibge6: str) -> str:
    soma = 0
    for posicao, caractere in enumerate(ibge6):
        produto = int(caractere) * (1 + posicao % 2)
        soma += produto // 10 + produto % 10
    return str((10 - soma % 10) % 10)


def gravar_territorio(destino: Path, extra: str | None = None) -> Path:
    codigos = [*MUNICIPIOS, extra] if extra else list(MUNICIPIOS)
    municipios = [
        {"ibge7": f"{c}{_digito(c)}", "ibge6": c, "nome": f"SINTETICO {c}", "regiao": "R1"}
        for c in codigos
    ]
    conteudo = {
        "territorio_id": "sintetico",
        "descricao": "Território SINTETICO dos testes.",
        "uf": "SP",
        "municipios": municipios,
        "proveniencia": "INFERIDA",
        "confirmacao": "A_CONFIRMAR",
        "fontes": [
            {
                "doc_id": "SINTETICO",
                "titulo": "Fixture sintética",
                "estado": "PENDENTE",
                "proveniencia": "INFERIDA",
                "confirmacao": "A_CONFIRMAR",
            }
        ],
    }
    destino.write_text(json.dumps(conteudo), encoding="utf-8")
    return destino


def _itens(*, sigtap_fev_ausente: bool, concorrente: bool) -> dict[str, _Item]:
    sem = ResultadoTentativa.NAO_ENCONTRADO
    itens = {
        f"pa_{p}": observar(FamiliaFonte.SIA_PA, FEVEREIRO, f"pa-{p}", 1, parte=p) for p in _PARTES
    }
    if concorrente:
        itens["pa_a2"] = observar(FamiliaFonte.SIA_PA, FEVEREIRO, "pa-a-outra", 2, parte="a")
    itens["cnes_jan"] = observar(FamiliaFonte.CNES_PF, JANEIRO, "cnes-jan", 1)
    itens["cnes_fev"] = observar(FamiliaFonte.CNES_PF, FEVEREIRO, "cnes-fev", 1)
    itens["sigtap_jan"] = observar(FamiliaFonte.SIGTAP, JANEIRO, "sigtap-jan", 1, uf=None)
    resultado = sem if sigtap_fev_ausente else ResultadoTentativa.OBTIDO
    itens["sigtap_fev"] = observar(
        FamiliaFonte.SIGTAP, FEVEREIRO, "sigtap-fev", 1, uf=None, resultado=resultado
    )
    return itens


def _linha(artefato: str, indice: int, **campos: str | None) -> dict[str, object]:
    base: dict[str, object] = {
        "row_id": f"{artefato}#{indice}",
        "artifact_id": artefato,
        "instrumento": "C",
        "procedimento": _PROCEDIMENTO,
        "cbo": _CBO,
        "cnes": _CNES,
        "competencia_atendimento": JANEIRO,
        "competencia_processamento": FEVEREIRO,
        "municipio_estabelecimento": MUNICIPIOS[0],
    }
    return base | campos


def _producao(artefato: str, parte: str, opcoes: dict[str, bool]) -> list[dict[str, object]]:
    """Linha 0 igual nas duas partes (mesmo conteúdo físico); a tem uma linha fora do território."""
    linhas = [_linha(artefato, 0)]
    if parte == "a":
        linhas.append(_linha(artefato, 1, competencia_atendimento=FEVEREIRO))
        atendimento = None if opcoes["fora_com_atendimento_nulo"] else JANEIRO
        linhas.append(
            _linha(
                artefato,
                2,
                municipio_estabelecimento=MUNICIPIO_FORA,
                competencia_atendimento=atendimento,
            )
        )
        if opcoes["municipio_nulo"]:
            linhas.append(_linha(artefato, 3, municipio_estabelecimento=None))
    return linhas


def _auxiliares(artefato: str, fonte: str, competencia: str) -> dict[str, list[dict[str, object]]]:
    if fonte == "CNES_PF":
        cbo = _CBO if competencia == JANEIRO else "223505"
        linha = {"artifact_id": artefato, "competencia_arquivo": competencia, "cnes": _CNES}
        return {"cnes_estab_cbo.v1": [linha | {"cbo": cbo, "n_vinculos": 1}]}
    base = {
        "artifact_id": artefato,
        "dt_competencia": competencia,
        "co_procedimento": _PROCEDIMENTO,
    }
    return {
        "sigtap_proc_ocupacao.v1": [base | {"co_ocupacao": _CBO}],
        "sigtap_proc_registro.v1": [base | {"co_registro": "01"}],
        "sigtap_procedimento.v1": [dict(base)],
    }


_TIPOS_ARROW = {
    TipoCanonico.TEXTO: pa.string(),
    TipoCanonico.INTEIRO: pa.int64(),
    TipoCanonico.DECIMAL: pa.decimal128(18, 2),
    TipoCanonico.DATA: pa.date32(),
    TipoCanonico.BOOLEANO: pa.bool_(),
}


def _gravar_completo(
    caminho: Path,
    schema_id: str,
    linhas: list[dict[str, object]],
    artefatos: tuple[str, ...],
    *,
    sem: frozenset[str] = frozenset(),
) -> DatasetRef:
    """Todas as colunas do esquema canônico, com os tipos físicos do ingest (como o T04 grava)."""
    campos = [
        (c.nome, _TIPOS_ARROW[c.tipo])
        for c in carregar_esquema(schema_id).colunas
        if c.nome not in sem
    ]
    ref = gravar_dataset(caminho, schema_id, linhas, artefatos, colunas=tuple(n for n, _ in campos))
    tabela = pa.Table.from_pylist(
        [{nome: linha.get(nome) for nome, _ in campos} for linha in linhas], pa.schema(campos)
    )
    pq.write_table(tabela, caminho)
    return reemitir(ref)


def _datasets(pasta: Path, itens: dict[str, _Item], opcoes: dict[str, bool]) -> list[DatasetRef]:
    refs = []
    for nome, (_, versao) in sorted(itens.items()):
        if versao is None:
            continue
        artefato, chave = versao.artifact_id, versao.chave
        if chave.fonte is FamiliaFonte.SIA_PA:
            linhas = _producao(artefato, str(chave.parte), opcoes)
            sem = frozenset({"municipio_estabelecimento"} if opcoes["sem_coluna_municipio"] else ())
            destino = pasta / f"{nome}.sia_pa.parquet"
            refs.append(_gravar_completo(destino, "sia_pa.v1", linhas, (artefato,), sem=sem))
            continue
        competencia = str(chave.competencia_arquivo)
        for schema_id, linhas in _auxiliares(artefato, chave.fonte.value, competencia).items():
            destino = pasta / f"{nome}.{schema_id}.parquet"
            refs.append(_gravar_completo(destino, schema_id, linhas, (artefato,)))
    return refs


def _cobertura(
    pasta: Path, refs: list[DatasetRef], incompleto: dict[str, str] | None
) -> DatasetRef:
    """Cobertura da ingestão pelo `build_coverage` real, sobre a produção sem recorte."""
    sia_pa = [ref for ref in refs if ref.schema_id == "sia_pa.v1"]
    auxiliares = [ref for ref in refs if ref.schema_id != "sia_pa.v1"]
    return build_coverage(
        sia_pa,
        auxiliares,
        [JANEIRO, FEVEREIRO],
        pasta / "cobertura",
        origem_dados=OrigemDados.SINTETICO,
        sia_pa_incompleto=incompleto,
    )


def _competencia_inteira(ref: DatasetRef) -> DatasetRef:
    """Cobertura com `competencia` física BIGINT e `DatasetRef` coerente com esse conteúdo."""
    tabela = pq.read_table(ref.caminho)
    posicao = tabela.column_names.index("competencia")
    inteira = pa.array([int(v) for v in tabela.column("competencia").to_pylist()], pa.int64())
    pq.write_table(tabela.set_column(posicao, "competencia", inteira), ref.caminho)
    return reemitir(ref)


def _gravar_config(
    raiz: Path, territorio: Path, competencias: tuple[str, ...], corte: str | None
) -> Path:
    config: dict[str, object] = {
        "versao": "1",
        "runtime": {
            "raiz_manifestos": str(raiz / "manifests"),
            "raiz_saidas": str(raiz / "outputs"),
        },
        "piloto": {
            "uf": "SP",
            "competencias_processamento": list(competencias),
            "territorio": str(territorio),
            "familias_fontes": ["SIA_PA", "CNES_PF", "SIGTAP"],
        },
    }
    if corte is not None:
        config["corte_observacao"] = corte
    caminho = raiz / "config.yaml"
    caminho.write_text(json.dumps(config), encoding="utf-8")
    return caminho


def montar_ingest(
    raiz: Path,
    *,
    sigtap_fev_ausente: bool = False,
    concorrente: bool = False,
    sem_cobertura: bool = False,
    sem_manifesto: bool = False,
    producao_repetida: bool = False,
    corte: str | None = None,
    auxiliar_divergente: bool = False,
    cobertura_com_tipo_invalido: bool = False,
    municipio_extra: str | None = None,
    competencias_piloto: tuple[str, ...] = (JANEIRO, FEVEREIRO),
    sem_coluna_municipio: bool = False,
    municipio_nulo: bool = False,
    fora_com_atendimento_nulo: bool = False,
    sia_pa_incompleto: dict[str, str] | None = None,
) -> MundoIngest:
    """Manifesto, pasta `execucao_*` com `datasets.jsonl`, território e config (SINTETICO)."""
    manifestos, saidas = raiz / "manifests", raiz / "outputs"
    pasta = saidas / "ingest" / "execucao_sintetica"
    pasta.mkdir(parents=True)
    manifestos.mkdir()
    itens = _itens(sigtap_fev_ausente=sigtap_fev_ausente, concorrente=concorrente)
    manifesto = manifestos / NOME_MANIFESTO_AQUISICAO
    if not sem_manifesto:
        registro = Manifesto(manifesto)
        for observacao, versao in itens.values():
            registro.registrar(observacao, versao)
    opcoes = {
        "municipio_nulo": municipio_nulo,
        "sem_coluna_municipio": sem_coluna_municipio,
        "fora_com_atendimento_nulo": fora_com_atendimento_nulo,
    }
    refs = _datasets(pasta, itens, opcoes)
    if not (sem_cobertura or sem_coluna_municipio):
        refs.append(_cobertura(pasta, refs, sia_pa_incompleto))
    if producao_repetida:
        refs.append(next(ref for ref in refs if ref.schema_id == "sia_pa.v1"))
    if cobertura_com_tipo_invalido:
        indice = next(i for i, ref in enumerate(refs) if ref.schema_id == "cobertura.v1")
        refs[indice] = _competencia_inteira(refs[indice])
    if auxiliar_divergente:
        indice = max(i for i, ref in enumerate(refs) if ref.schema_id == "sigtap_procedimento.v1")
        refs[indice] = refs[indice].model_copy(update={"linhas": refs[indice].linhas + 1})
    linhas = "".join(f"{ref.model_dump_json()}\n" for ref in refs)
    (pasta / "datasets.jsonl").write_text(linhas, encoding="utf-8")
    territorio = gravar_territorio(raiz / "territorio.yaml", municipio_extra)
    caminho_config = _gravar_config(raiz, territorio, competencias_piloto, corte)
    return MundoIngest(pasta, caminho_config, manifesto, saidas / "runs")
