"""Fábricas SINTETICO de SIA-PA canônico, rótulos e território para o protocolo (T10/T11).

Todos os valores são fictícios: códigos, competências e rótulos são escolhidos só para exercitar
partições, atributos e métricas. Nada aqui provém de arquivo real do DATASUS.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.config import RunConfig, RuntimeConfig
from sustemporal.contracts.experiment import CohortSpec, SplitManifest, SplitSpec
from sustemporal.contracts.records import DatasetRef, TipoCanonico, calcular_dataset_id
from sustemporal.duck import conectar
from sustemporal.evaluation.split import build_splits
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from pathlib import Path

MUNICIPIO_DENTRO = "354140"
MUNICIPIO_DENTRO_7 = "3541406"
MUNICIPIO_FORA = "355030"

_TIPOS_ARROW = {
    TipoCanonico.TEXTO: pa.string(),
    TipoCanonico.INTEIRO: pa.int64(),
    TipoCanonico.DECIMAL: pa.decimal128(38, 2),
    TipoCanonico.BOOLEANO: pa.bool_(),
    TipoCanonico.DATA: pa.date32(),
}


def artefato(semente: str) -> str:
    return f"art_{hashlib.sha256(semente.encode()).hexdigest()}"


@dataclass
class LinhaPa:
    artifact_id: str
    indice: int
    competencia_processamento: str | None = "201801"
    competencia_atendimento: str | None = "201801"
    cnes: str | None = "0000001"
    municipio_estabelecimento: str | None = MUNICIPIO_DENTRO
    procedimento: str | None = "0301010072"
    instrumento: str | None = "C"
    cbo: str | None = "225125"
    carater_atendimento: str | None = "01"
    sexo: str | None = "M"
    idade: int | None = 40
    quantidade_apresentada: int | None = 1
    deletado: bool = False
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def row_id(self) -> str:
        return f"{self.artifact_id}#{self.indice}"

    def valores(self) -> dict[str, object]:
        base = {
            "row_id": self.row_id,
            "artifact_id": self.artifact_id,
            "indice_registro": self.indice,
            "deletado": self.deletado,
            "competencia_processamento": self.competencia_processamento,
            "competencia_atendimento": self.competencia_atendimento,
            "cnes": self.cnes,
            "municipio_estabelecimento": self.municipio_estabelecimento,
            "procedimento": self.procedimento,
            "instrumento": self.instrumento,
            "cbo": self.cbo,
            "carater_atendimento": self.carater_atendimento,
            "sexo": self.sexo,
            "idade": self.idade,
            "quantidade_apresentada": self.quantidade_apresentada,
        }
        return {**base, **self.extras}


def _gravar(
    linhas: list[dict[str, object]],
    schema_id: str,
    destino: Path,
    *,
    artifact_ids: tuple[str, ...],
    origem: OrigemDados,
) -> DatasetRef:
    esquema = carregar_esquema(schema_id)
    colunas = [c.nome for c in esquema.colunas]
    tabela = pa.table(
        {
            c.nome: pa.array([linha.get(c.nome) for linha in linhas], _TIPOS_ARROW[c.tipo])
            for c in esquema.colunas
        }
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(tabela, destino)
    con = conectar(RuntimeConfig(duckdb_threads=1))
    try:
        con.execute("CREATE TABLE lida AS SELECT * FROM read_parquet($c)", {"c": str(destino)})
        hash_logico = hash_logico_relacao(con, "lida", colunas)
    finally:
        con.close()
    return DatasetRef(
        dataset_id=calcular_dataset_id(schema_id, hash_logico, artifact_ids),
        schema_id=schema_id,
        caminho=str(destino),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=artifact_ids,
        origem_dados=origem,
        produzido_por="tests.fixtures.protocolo_dados",
    )


def gravar_sia_pa(
    linhas: list[LinhaPa], destino: Path, *, origem: OrigemDados = OrigemDados.SINTETICO
) -> DatasetRef:
    artefatos = tuple(sorted({linha.artifact_id for linha in linhas}))
    valores = [linha.valores() for linha in linhas]
    return _gravar(valores, "sia_pa.v1", destino, artifact_ids=artefatos, origem=origem)


def fontes_identidade(linhas: list[LinhaPa]) -> dict[str, str]:
    return {linha.artifact_id: linha.artifact_id for linha in linhas}


def gravar_rotulos(
    rotulos: dict[str, str],
    destino: Path,
    *,
    origem: OrigemDados = OrigemDados.SINTETICO,
) -> DatasetRef:
    linhas = [
        {"row_id": row_id, "rotulo": rotulo, "codebook_id": "SINTETICO", "contradicoes": ""}
        for row_id, rotulo in sorted(rotulos.items())
    ]
    artefatos = tuple(sorted({row_id.split("#")[0] for row_id in rotulos}))
    return _gravar(linhas, "sia_pa_rotulos.v1", destino, artifact_ids=artefatos, origem=origem)


def gravar_territorio(destino: Path) -> Path:
    destino.write_text(
        "territorio_id: sintetico\n"
        "descricao: Território SINTETICO de um município para testes.\n"
        "uf: SP\n"
        "proveniencia: INFERIDA\n"
        "confirmacao: A_CONFIRMAR\n"
        "fontes:\n"
        "  - doc_id: SINTETICO\n"
        "    titulo: Território fictício de teste\n"
        "    estado: PENDENTE\n"
        "    proveniencia: INFERIDA\n"
        "municipios:\n"
        f"  - ibge7: '{MUNICIPIO_DENTRO_7}'\n"
        f"    ibge6: '{MUNICIPIO_DENTRO}'\n"
        "    nome: Município fictício\n"
        "    regiao: Região fictícia\n",
        encoding="utf-8",
    )
    return destino


def coorte(territorio: Path, **campos: object) -> CohortSpec:
    base: dict[str, object] = {
        "cohort_id": "coorte_sintetica",
        "uf": "SP",
        "territorio": str(territorio),
        "pertenca": "FIXA",
        "inicio": "201801",
        "fim": "202512",
    }
    return CohortSpec.model_validate({**base, **campos})


SPEC_PADRAO = SplitSpec.model_validate(
    {
        "intervalos": [
            {"particao": "DESENVOLVIMENTO", "inicio": "201801", "fim": "202212"},
            {"particao": "CALIBRACAO", "inicio": "202301", "fim": "202312"},
            {"particao": "TESTE", "inicio": "202401", "fim": "202512"},
        ]
    }
)
PROC_REJEITADO = "0000000001"
PROC_APROVADO = "0000000002"


@dataclass(frozen=True)
class Cenario:
    split: SplitManifest
    rotulos: DatasetRef
    config: RunConfig
    linhas: tuple[LinhaPa, ...]
    rotulo_por_row: dict[str, str]


_INVERSO = {"NAO_APROVADO": "APROVADO_TOTAL", "APROVADO_TOTAL": "NAO_APROVADO"}


def _linhas_da_competencia(
    competencia: str, n: int, *, invertida: bool = False
) -> list[tuple[LinhaPa, str]]:
    art = artefato(f"pa_{competencia}")
    saida = []
    for indice in range(n):
        rejeitado = indice % 3 == 0
        linha = LinhaPa(
            art,
            indice,
            competencia_processamento=competencia,
            competencia_atendimento=competencia,
            cnes=f"{indice % 4:07d}",
            procedimento=PROC_REJEITADO if rejeitado else PROC_APROVADO,
            idade=20 + indice % 50,
            quantidade_apresentada=1 + indice % 3,
        )
        rotulo = "NAO_APROVADO" if rejeitado else "APROVADO_TOTAL"
        if indice % 7 == 6:
            rotulo = "APROVADO_PARCIAL"
        if invertida:
            rotulo = _INVERSO.get(rotulo, rotulo)
        saida.append((linha, rotulo))
    return saida


def cenario_baseline(
    raiz: Path,
    *,
    competencias: tuple[str, ...] = ("201901", "202001", "202301", "202401"),
    n: int = 30,
    extras: tuple[tuple[LinhaPa, str], ...] = (),
    invertidas: tuple[str, ...] = (),
) -> Cenario:
    pares = [
        par for c in competencias for par in _linhas_da_competencia(c, n, invertida=c in invertidas)
    ]
    pares.extend(extras)
    linhas = tuple(linha for linha, _ in pares)
    dataset = gravar_sia_pa(list(linhas), raiz / "entrada" / "sia_pa.parquet")
    rotulos = gravar_rotulos(
        {linha.row_id: rotulo for linha, rotulo in pares}, raiz / "entrada" / "rotulos.parquet"
    )
    territorio = gravar_territorio(raiz / "territorio.yaml")
    split = build_splits(
        dataset,
        coorte(territorio),
        raiz / "split",
        spec=SPEC_PADRAO,
        fonte_por_artefato=fontes_identidade(list(linhas)),
        rotulos=rotulos,
    )
    config = RunConfig.model_validate({"versao": "1", "origem_dados": "SINTETICO"})
    return Cenario(split, rotulos, config, linhas, {linha.row_id: r for linha, r in pares})
