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
from sustemporal.contracts.base import FamiliaFonte
from tests.fixtures.regras_cenario import COLUNAS_REGISTRO, gravar_dataset, reemitir
from tests.fixtures.regras_lote import cobertura_lote
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion
    from sustemporal.contracts.records import DatasetRef

__all__ = ["MUNICIPIOS", "MUNICIPIO_FORA", "MundoIngest", "montar_ingest"]

JANEIRO, FEVEREIRO = "202301", "202302"
_PROCEDIMENTO, _CBO, _CNES = "0301010072", "225125", "1234567"
_PARTES = ("a", "b")
MUNICIPIOS = ("350010", "350020")
MUNICIPIO_FORA = "359990"
_COLUNAS_PRODUCAO = (*COLUNAS_REGISTRO, "municipio_estabelecimento")
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


def _territorio(destino: Path) -> Path:
    municipios = [
        {"ibge7": f"{c}{_digito(c)}", "ibge6": c, "nome": f"SINTETICO {c}", "regiao": "R1"}
        for c in MUNICIPIOS
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


def _producao(artefato: str, parte: str) -> list[dict[str, object]]:
    """Linha 0 igual nas duas partes (mesmo conteúdo físico); a tem uma linha fora do território."""
    linhas = [_linha(artefato, 0)]
    if parte == "a":
        linhas.append(_linha(artefato, 1, competencia_atendimento=FEVEREIRO))
        linhas.append(_linha(artefato, 2, municipio_estabelecimento=MUNICIPIO_FORA))
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


def _datasets(pasta: Path, itens: dict[str, _Item], *, sem_cobertura: bool) -> list[DatasetRef]:
    refs = []
    for nome, (_, versao) in sorted(itens.items()):
        if versao is None:
            continue
        artefato, chave = versao.artifact_id, versao.chave
        if chave.fonte is FamiliaFonte.SIA_PA:
            linhas = _producao(artefato, str(chave.parte))
            destino = pasta / f"{nome}.sia_pa.parquet"
            refs.append(
                gravar_dataset(destino, "sia_pa.v1", linhas, (artefato,), colunas=_COLUNAS_PRODUCAO)
            )
            continue
        competencia = str(chave.competencia_arquivo)
        for schema_id, linhas in _auxiliares(artefato, chave.fonte.value, competencia).items():
            destino = pasta / f"{nome}.{schema_id}.parquet"
            refs.append(gravar_dataset(destino, schema_id, linhas, (artefato,)))
    if not sem_cobertura:
        cobertura = [dict(linha) for linha in cobertura_lote()]
        refs.append(gravar_dataset(pasta / "cobertura.parquet", "cobertura.v1", cobertura, ()))
    return refs


def _competencia_inteira(ref: DatasetRef) -> DatasetRef:
    """Cobertura com `competencia` física BIGINT e `DatasetRef` coerente com esse conteúdo."""
    tabela = pq.read_table(ref.caminho)
    posicao = tabela.column_names.index("competencia")
    inteira = pa.array([int(v) for v in tabela.column("competencia").to_pylist()], pa.int64())
    pq.write_table(tabela.set_column(posicao, "competencia", inteira), ref.caminho)
    return reemitir(ref)


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
    refs = _datasets(pasta, itens, sem_cobertura=sem_cobertura)
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
    config: dict[str, object] = {
        "versao": "1",
        "runtime": {"raiz_manifestos": str(manifestos), "raiz_saidas": str(saidas)},
        "piloto": {
            "uf": "SP",
            "competencias_processamento": [JANEIRO, FEVEREIRO],
            "territorio": str(_territorio(raiz / "territorio.yaml")),
            "familias_fontes": ["SIA_PA", "CNES_PF", "SIGTAP"],
        },
    }
    if corte is not None:
        config["corte_observacao"] = corte
    caminho_config = raiz / "config.yaml"
    caminho_config.write_text(json.dumps(config), encoding="utf-8")
    return MundoIngest(pasta, caminho_config, manifesto, saidas / "runs")
