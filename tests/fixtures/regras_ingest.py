"""Pasta de `sustemporal ingest` e manifesto de aquisição SINTETICOS para `validate --ingest`.

Produção SIA-PA de 202302 em duas partes (a e b) com uma linha física repetida entre elas e uma
linha de município fora do território; o catálogo de fontes declara as partes esperadas a e b.
CNES e SIGTAP de 202301 e 202302; o par (1234567, 225125) existe no CNES de janeiro e falta no de
fevereiro. Códigos IBGE sintéticos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.acquisition.cli import NOME_MANIFESTO_AQUISICAO
from sustemporal.acquisition.manifest import Manifesto
from sustemporal.contracts.artifacts import EstadoIntegridade, ResultadoTentativa
from sustemporal.contracts.base import FamiliaFonte, OrigemDados
from sustemporal.contracts.records import (
    DatasetRef,
    Reconciliacao,
    TipoCanonico,
    calcular_dataset_id,
)
from sustemporal.hashing import hash_logico_linhas
from sustemporal.ingest.coverage import build_coverage
from sustemporal.rules.catalog import carregar_esquema
from tests.fixtures.regras_cenario import reemitir
from tests.fixtures.temporal_registro import observar

if TYPE_CHECKING:
    from pathlib import Path

    from sustemporal.contracts.artifacts import ArtifactObservation, ArtifactVersion

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
_COLUNAS_OMITIDAS = {
    "sem_coluna_municipio": "municipio_estabelecimento",
    "sem_coluna_deletado": "deletado",
    "sem_coluna_artifact_id": "artifact_id",
}


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


def _itens(
    *,
    sigtap_fev_ausente: bool,
    concorrente: bool,
    concorrente_dia: int = 2,
    partes: tuple[str, ...] = _PARTES,
    em_quarentena: bool = False,
) -> dict[str, _Item]:
    sem = ResultadoTentativa.NAO_ENCONTRADO
    itens = {
        f"pa_{p}": observar(FamiliaFonte.SIA_PA, FEVEREIRO, f"pa-{p}", 1, parte=p) for p in partes
    }
    if em_quarentena:
        quarentena = EstadoIntegridade.QUARENTENA_CHECKSUM
        itens["pa_a"] = observar(
            FamiliaFonte.SIA_PA, FEVEREIRO, "pa-a", 1, parte="a", integridade_observada=quarentena
        )
    if concorrente:
        itens["pa_a2"] = observar(
            FamiliaFonte.SIA_PA, FEVEREIRO, "pa-a-outra", concorrente_dia, parte="a"
        )
    itens["cnes_jan"] = observar(FamiliaFonte.CNES_PF, JANEIRO, "cnes-jan", 1)
    itens["cnes_fev"] = observar(FamiliaFonte.CNES_PF, FEVEREIRO, "cnes-fev", 1)
    itens["sigtap_jan"] = observar(FamiliaFonte.SIGTAP, JANEIRO, "sigtap-jan", 1, uf=None)
    resultado = sem if sigtap_fev_ausente else ResultadoTentativa.OBTIDO
    itens["sigtap_fev"] = observar(
        FamiliaFonte.SIGTAP, FEVEREIRO, "sigtap-fev", 1, uf=None, resultado=resultado
    )
    return itens


def _linha(artefato: str, indice: int, **campos: object) -> dict[str, object]:
    base: dict[str, object] = {
        "row_id": f"{artefato}#{indice}",
        "artifact_id": artefato,
        "indice_registro": indice,
        "deletado": False,
        "instrumento": "C",
        "procedimento": _PROCEDIMENTO,
        "cbo": _CBO,
        "cnes": _CNES,
        "competencia_atendimento": JANEIRO,
        "competencia_processamento": FEVEREIRO,
        "municipio_estabelecimento": MUNICIPIOS[0],
    }
    return base | campos


def _colunas_ausentes(opcoes: dict[str, bool]) -> frozenset[str]:
    return frozenset(coluna for opcao, coluna in _COLUNAS_OMITIDAS.items() if opcoes[opcao])


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
        if opcoes["deletado_no_territorio"]:
            linhas.append(_linha(artefato, 4, deletado=True))
        if opcoes["linha_fora_do_piloto"]:
            linhas.append(_linha(artefato, 6, competencia_processamento="202303"))
        if opcoes["deletado_fora"]:
            linhas.append(
                _linha(artefato, 5, deletado=True, municipio_estabelecimento=MUNICIPIO_FORA)
            )
        if opcoes["municipio_nulo"]:
            linhas.append(_linha(artefato, 3, municipio_estabelecimento=None))
        if opcoes["deletado_nulo"]:
            linhas.append(_linha(artefato, 7, deletado=None))
        if opcoes["linha_de_janeiro"]:
            linhas.append(_linha(artefato, 8, competencia_processamento=JANEIRO))
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
    colunas = [c for c in carregar_esquema(schema_id).colunas if c.nome not in sem]
    campos = [(c.nome, _TIPOS_ARROW[c.tipo]) for c in colunas]
    tabela = pa.Table.from_pylist(
        [{nome: linha.get(nome) for nome, _ in campos} for linha in linhas], pa.schema(campos)
    )
    pq.write_table(tabela, caminho)
    nomes = [nome for nome, _ in campos]
    valores = [tabela.column(nome).to_pylist() for nome in nomes]
    hash_logico = hash_logico_linhas(nomes, zip(*valores, strict=True))
    return DatasetRef(
        dataset_id=calcular_dataset_id(schema_id, hash_logico, artefatos),
        schema_id=schema_id,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=tabela.num_rows,
        artifact_ids=artefatos,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="fixture_ingest_sintetica",
    )


def _datasets(pasta: Path, itens: dict[str, _Item], opcoes: dict[str, bool]) -> list[DatasetRef]:
    refs = []
    for nome, (_, versao) in sorted(itens.items()):
        if versao is None:
            continue
        artefato, chave = versao.artifact_id, versao.chave
        if chave.fonte is FamiliaFonte.SIA_PA:
            linhas = _producao(artefato, str(chave.parte), opcoes)
            destino = pasta / f"{nome}.sia_pa.parquet"
            sem = _colunas_ausentes(opcoes)
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


def _motivo_malformado(ref: DatasetRef) -> DatasetRef:
    """Uma célula com marca `sia_pa_incompleto` fora do formato de `_marcar_incompleto`."""
    tabela = pq.read_table(ref.caminho)
    motivos = tabela.column("motivo").to_pylist()
    motivos[0] = "sia_pa_incompleto sem_competencia"
    posicao = tabela.column_names.index("motivo")
    pq.write_table(tabela.set_column(posicao, "motivo", pa.array(motivos)), ref.caminho)
    return reemitir(ref)


def _competencia_inteira(ref: DatasetRef) -> DatasetRef:
    """Cobertura com `competencia` física BIGINT e `DatasetRef` coerente com esse conteúdo."""
    tabela = pq.read_table(ref.caminho)
    posicao = tabela.column_names.index("competencia")
    inteira = pa.array([int(v) for v in tabela.column("competencia").to_pylist()], pa.int64())
    pq.write_table(tabela.set_column(posicao, "competencia", inteira), ref.caminho)
    return reemitir(ref)


def _com_perda(refs: list[DatasetRef], versao: ArtifactVersion | None) -> list[DatasetRef]:
    """O conjunto da versão declara linhas descartadas com motivo de perda (fora de _SEM_PERDA)."""
    assert versao is not None
    perda = Reconciliacao(fisicos=2, canonicas=1, excluidas_por_motivo={"cnes_invalido": 1})
    return [
        ref.model_copy(update={"reconciliacao": perda})
        if ref.artifact_ids == (versao.artifact_id,)
        else ref
        for ref in refs
    ]


def _trocar_artefatos(refs: list[DatasetRef], schema_id: str) -> list[DatasetRef]:
    """Dois conjuntos do esquema declaram cada um o artefato do outro (linhagem trocada)."""
    indices = [i for i, ref in enumerate(refs) if ref.schema_id == schema_id]
    primeiro, segundo = (refs[i] for i in indices[:2])
    trocados = list(refs)
    for indice, ref, outro in ((indices[0], primeiro, segundo), (indices[1], segundo, primeiro)):
        dataset_id = calcular_dataset_id(schema_id, ref.hash_logico, outro.artifact_ids)
        trocados[indice] = ref.model_copy(
            update={"artifact_ids": outro.artifact_ids, "dataset_id": dataset_id}
        )
    return trocados


def _producao_de_outra_fonte(
    pasta: Path, versao: ArtifactVersion | None, opcoes: dict[str, bool]
) -> DatasetRef:
    """Um `sia_pa.v1` cujas linhas declaram um artefato do CNES (mesma UF e competência)."""
    assert versao is not None
    linhas = _producao(versao.artifact_id, "b", opcoes)
    destino = pasta / "cnes_como_producao.sia_pa.parquet"
    return _gravar_completo(destino, "sia_pa.v1", linhas, (versao.artifact_id,))


def _sem_producao_da_versao(
    refs: list[DatasetRef], versao: ArtifactVersion | None
) -> list[DatasetRef]:
    """`datasets.jsonl` sem o conjunto da produção da versão; a cobertura já a considerou."""
    assert versao is not None
    return [
        ref
        for ref in refs
        if not (ref.schema_id == "sia_pa.v1" and ref.artifact_ids == (versao.artifact_id,))
    ]


def _indice(refs: list[DatasetRef], schema_id: str) -> int:
    return max(i for i, ref in enumerate(refs) if ref.schema_id == schema_id)


def _com_defeitos(refs: list[DatasetRef], defeitos: dict[str, bool]) -> list[DatasetRef]:
    """Defeitos de entrada injetados nos `DatasetRef` da pasta, um por opção."""
    refs = list(refs)
    if defeitos["producao_repetida"]:
        refs.append(next(ref for ref in refs if ref.schema_id == "sia_pa.v1"))
    if defeitos["cobertura_motivo_malformado"]:
        indice = _indice(refs, "cobertura.v1")
        refs[indice] = _motivo_malformado(refs[indice])
    if defeitos["cobertura_com_tipo_invalido"]:
        indice = _indice(refs, "cobertura.v1")
        refs[indice] = _competencia_inteira(refs[indice])
    if defeitos["auxiliares_trocados"]:
        refs = _trocar_artefatos(refs, "cnes_estab_cbo.v1")
    if defeitos["auxiliar_divergente"]:
        indice = _indice(refs, "sigtap_procedimento.v1")
        refs[indice] = refs[indice].model_copy(update={"linhas": refs[indice].linhas + 1})
    return refs


def _gravar_catalogo(destino: Path, *, declarar_partes: bool = True) -> Path:
    """Catálogo de fontes SINTETICO; o SIA-PA de fevereiro espera as partes a e b, se declaradas."""
    fonte = {
        "fonte": "SIA_PA",
        "diretorio": "file:///sintetico/",
        "padrao_nome": r"PA{uf}{aamm}(?P<parte>[a-z]|_[0-9]+)?\.dbc",
        "formato": "DBC",
        "canal": "ATUAL",
        "multipartes": "true",
        "partes_esperadas": {FEVEREIRO: list(_PARTES)} if declarar_partes else {},
        "tamanho_maximo_bytes": "1000",
        "proveniencia": "INFERIDA",
        "confirmacao": "A_CONFIRMAR",
    }
    destino.write_text(json.dumps({"versao": "1", "fontes": [fonte]}), encoding="utf-8")
    return destino


def _gravar_config(
    raiz: Path, territorio: Path, competencias: tuple[str, ...], corte: str | None, catalogo: Path
) -> Path:
    config: dict[str, object] = {
        "versao": "1",
        "catalogos": {"fontes": str(catalogo)},
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
    deletado_no_territorio: bool = False,
    auxiliares_trocados: bool = False,
    deletado_fora: bool = False,
    cnes_fev_com_perda: bool = False,
    concorrente_so_no_registro: int | None = None,
    linha_fora_do_piloto: bool = False,
    cobertura_motivo_malformado: bool = False,
    producao_com_artefato_cnes: bool = False,
    parte_b_so_no_registro: bool = False,
    deletado_nulo: bool = False,
    sem_coluna_deletado: bool = False,
    sem_coluna_artifact_id: bool = False,
    sem_parte_b: bool = False,
    linha_de_janeiro: bool = False,
    partes_sem_declaracao: bool = False,
    producao_em_quarentena: bool = False,
) -> MundoIngest:
    """Manifesto, pasta `execucao_*` com `datasets.jsonl`, território e config (SINTETICO)."""
    manifestos, saidas = raiz / "manifests", raiz / "outputs"
    pasta = saidas / "ingest" / "execucao_sintetica"
    pasta.mkdir(parents=True)
    manifestos.mkdir()
    no_registro = concorrente_so_no_registro is not None
    itens = _itens(
        sigtap_fev_ausente=sigtap_fev_ausente,
        concorrente=concorrente or no_registro,
        concorrente_dia=concorrente_so_no_registro or 2,
        partes=_PARTES[:1] if sem_parte_b else _PARTES,
        em_quarentena=producao_em_quarentena,
    )
    manifesto = manifestos / NOME_MANIFESTO_AQUISICAO
    if not sem_manifesto:
        registro = Manifesto(manifesto)
        for observacao, versao in itens.values():
            registro.registrar(observacao, versao)
    opcoes = {
        "municipio_nulo": municipio_nulo,
        "sem_coluna_municipio": sem_coluna_municipio,
        "fora_com_atendimento_nulo": fora_com_atendimento_nulo,
        "deletado_no_territorio": deletado_no_territorio,
        "deletado_fora": deletado_fora,
        "linha_fora_do_piloto": linha_fora_do_piloto,
        "deletado_nulo": deletado_nulo,
        "sem_coluna_deletado": sem_coluna_deletado,
        "sem_coluna_artifact_id": sem_coluna_artifact_id,
        "linha_de_janeiro": linha_de_janeiro,
    }
    na_pasta = {k: v for k, v in itens.items() if not (no_registro and k == "pa_a2")}
    refs = _datasets(pasta, na_pasta, opcoes)
    if cnes_fev_com_perda:
        refs = _com_perda(refs, itens["cnes_fev"][1])
    if not (sem_cobertura or _colunas_ausentes(opcoes)):
        refs.append(_cobertura(pasta, refs, sia_pa_incompleto))
    if producao_com_artefato_cnes:
        refs.append(_producao_de_outra_fonte(pasta, itens["cnes_fev"][1], opcoes))
    if parte_b_so_no_registro:
        refs = _sem_producao_da_versao(refs, itens["pa_b"][1])
    defeitos = {
        "producao_repetida": producao_repetida,
        "cobertura_motivo_malformado": cobertura_motivo_malformado,
        "cobertura_com_tipo_invalido": cobertura_com_tipo_invalido,
        "auxiliares_trocados": auxiliares_trocados,
        "auxiliar_divergente": auxiliar_divergente,
    }
    refs = _com_defeitos(refs, defeitos)
    linhas = "".join(f"{ref.model_dump_json()}\n" for ref in refs)
    (pasta / "datasets.jsonl").write_text(linhas, encoding="utf-8")
    territorio = gravar_territorio(raiz / "territorio.yaml", municipio_extra)
    catalogo = _gravar_catalogo(raiz / "fontes.yaml", declarar_partes=not partes_sem_declaracao)
    caminho_config = _gravar_config(raiz, territorio, competencias_piloto, corte, catalogo)
    return MundoIngest(pasta, caminho_config, manifesto, saidas / "runs")
