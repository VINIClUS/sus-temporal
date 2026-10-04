"""Cenário SINTETICO de partições SIA-PA e rótulos para a anotação cega (T12).

Gera Parquet com todas as colunas de sia_pa.v1 (tipos canônicos) por DuckDB; valores inventados,
sem relação com registros reais.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import pyarrow as pa
import pyarrow.parquet as pq

from sustemporal.contracts import (
    DatasetRef,
    IntervaloParticao,
    OrigemDados,
    Particao,
    RunConfig,
    RuntimeConfig,
    SplitManifest,
    SplitSpec,
    calcular_dataset_id,
)
from sustemporal.duck import conectar
from sustemporal.hashing import hash_logico_relacao
from sustemporal.rules.catalog import carregar_esquema

if TYPE_CHECKING:
    from pathlib import Path

ARTEFATO_DEV = f"art_{'1' * 64}"
ARTEFATO_TESTE = f"art_{'2' * 64}"
INSTRUMENTOS = ("BPA_C", "BPA_I", "APAC")
CNES = ("1000001", "1000002", "1000003", "1000004", "1000005")
ROTULOS = ("NAO_APROVADO", "NAO_APROVADO", "APROVADO_TOTAL", "APROVADO_PARCIAL")
_ARROW_TIPO = {
    "TEXTO": pa.string(),
    "INTEIRO": pa.int64(),
    "BOOLEANO": pa.bool_(),
    "DECIMAL": pa.decimal128(38, 2),
    "DATA": pa.date32(),
}


def _gravar(
    caminho: Path, schema_id: str, linhas: list[dict[str, object]], artefatos: tuple[str, ...]
) -> DatasetRef:
    esquema = carregar_esquema(schema_id)
    colunas = [c.nome for c in esquema.colunas]
    tipos = pa.schema([(c.nome, _ARROW_TIPO[c.tipo.value]) for c in esquema.colunas])
    tabela = pa.Table.from_pylist([{c: linha.get(c) for c in colunas} for linha in linhas], tipos)
    pq.write_table(tabela, caminho)
    with closing(conectar(RuntimeConfig(duckdb_threads=1))) as con:
        con.execute("CREATE TABLE t AS SELECT * FROM read_parquet($c)", {"c": str(caminho)})
        hash_logico = hash_logico_relacao(con, "t", colunas)
    return DatasetRef(
        dataset_id=calcular_dataset_id(schema_id, hash_logico, artefatos),
        schema_id=schema_id,
        caminho=str(caminho),
        hash_logico=hash_logico,
        linhas=len(linhas),
        artifact_ids=artefatos,
        origem_dados=OrigemDados.SINTETICO,
        produzido_por="fixture_anotacao_sintetica",
    )


def registro(row_id: str, artefato: str, indice: int, **campos: object) -> dict[str, object]:
    base: dict[str, object] = {
        "row_id": row_id,
        "artifact_id": artefato,
        "membro": "PASP2401.dbf",
        "indice_registro": indice,
        "deletado": False,
        "cnes": CNES[indice % len(CNES)],
        "municipio_estabelecimento": "354140",
        "competencia_processamento": "202403",
        "competencia_atendimento": "202403",
        "procedimento": "0301010072",
        "instrumento": INSTRUMENTOS[indice % len(INSTRUMENTOS)],
        "cbo": "225125",
        "idade": 40,
        "sexo": "F",
        "pa_munpcn": "354140",
        "pa_racacor": "01",
        "quantidade_apresentada": 1,
        "quantidade_aprovada": 0,
        "valor_apresentado": Decimal("10.00"),
        "valor_aprovado": Decimal("0.00"),
    }
    return base | campos


def gerar_registros(
    prefixo: str, artefato: str, quantidade: int, competencias: tuple[str, ...]
) -> list[dict[str, object]]:
    linhas = []
    for i in range(quantidade):
        proc = competencias[i % len(competencias)]
        defasagem = (0, 0, 1, 2, 5)[i % 5]
        ano, mes = int(proc[:4]), int(proc[4:])
        total = ano * 12 + mes - 1 - defasagem
        atend = f"{total // 12:04d}{total % 12 + 1:02d}"
        linhas.append(
            registro(
                f"{prefixo}{i:05d}",
                artefato,
                i,
                competencia_processamento=proc,
                competencia_atendimento=None if i % 17 == 0 else atend,
            )
        )
    return linhas


def rotulo_de(indice: int) -> str:
    return ROTULOS[indice % len(ROTULOS)]


def gravar_rotulos(caminho: Path, linhas: list[dict[str, object]]) -> DatasetRef:
    rotulos = [
        {
            "row_id": linha["row_id"],
            "pa_indica_bruto": "0",
            "rotulo": rotulo_de(i),
            "codebook_id": "sia_pa_indica.v1",
            "contradicoes": "",
        }
        for i, linha in enumerate(linhas)
    ]
    return _gravar(caminho, "sia_pa_rotulos.v1", rotulos, (ARTEFATO_DEV, ARTEFATO_TESTE))


@dataclass(frozen=True)
class CenarioAnotacao:
    labels: DatasetRef
    split: SplitManifest
    particoes: dict[Particao, DatasetRef]
    completo: DatasetRef
    config: RunConfig
    linhas_teste: list[dict[str, object]]


def montar_cenario(
    raiz: Path,
    *,
    n_dev: int = 80,
    n_teste: int = 1200,
    linhas_teste: list[dict[str, object]] | None = None,
) -> CenarioAnotacao:
    raiz.mkdir(parents=True, exist_ok=True)
    dev = gerar_registros("d", ARTEFATO_DEV, n_dev, ("201905", "202011"))
    teste = (
        linhas_teste
        if linhas_teste is not None
        else gerar_registros("t", ARTEFATO_TESTE, n_teste, ("202402", "202407", "202503"))
    )
    vazio = [registro("c00000", ARTEFATO_DEV, 0, competencia_processamento="202306")]
    particoes = {
        Particao.DESENVOLVIMENTO: _gravar(raiz / "dev.parquet", "sia_pa.v1", dev, (ARTEFATO_DEV,)),
        Particao.CALIBRACAO: _gravar(raiz / "cal.parquet", "sia_pa.v1", vazio, (ARTEFATO_DEV,)),
        Particao.TESTE: _gravar(raiz / "teste.parquet", "sia_pa.v1", teste, (ARTEFATO_TESTE,)),
    }
    completo = _gravar(
        raiz / "completo.parquet", "sia_pa.v1", dev + vazio + teste, (ARTEFATO_DEV, ARTEFATO_TESTE)
    )
    labels = gravar_rotulos(raiz / "rotulos.parquet", dev + vazio + teste)
    intervalos = (
        IntervaloParticao.model_validate(
            {"particao": Particao.DESENVOLVIMENTO, "inicio": "201801", "fim": "202212"}
        ),
        IntervaloParticao.model_validate(
            {"particao": Particao.CALIBRACAO, "inicio": "202301", "fim": "202312"}
        ),
        IntervaloParticao.model_validate(
            {"particao": Particao.TESTE, "inicio": "202401", "fim": "202512"}
        ),
    )
    split = SplitManifest(
        split_id="spl_sintetico",
        spec=SplitSpec(intervalos=intervalos),
        dataset_hash=completo.hash_logico,
        linhas_por_particao={p: d.linhas for p, d in particoes.items()},
        hash_por_particao={p: d.hash_logico for p, d in particoes.items()},
        artefatos_teste=(ARTEFATO_TESTE,),
    )
    config = RunConfig(versao="1", origem_dados=OrigemDados.SINTETICO, semente=2027)
    return CenarioAnotacao(labels, split, particoes, completo, config, teste)
