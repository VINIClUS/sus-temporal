"""Contratos sintéticos mínimos e válidos para compor congelamentos nos testes."""

from sustemporal.contracts.base import OrigemDados
from sustemporal.contracts.experiment import (
    Atributo,
    FeatureSpec,
    IntervaloParticao,
    Particao,
    SplitManifest,
    SplitSpec,
)
from sustemporal.contracts.records import DatasetRef, calcular_dataset_id

ARTEFATO = f"art_{'a' * 64}"
HASH_LOGICO = f"lh1:{'d' * 64}"
PARTICOES_DO_PLANO = (
    (Particao.DESENVOLVIMENTO, "201801", "202212"),
    (Particao.CALIBRACAO, "202301", "202312"),
    (Particao.TESTE, "202401", "202512"),
)


def dataset_sintetico(linhas: int = 10) -> DatasetRef:
    """`DatasetRef` do SIA-PA com rótulo REAL só de teste e conteúdo sintético (sem dado real)."""
    return DatasetRef(
        dataset_id=calcular_dataset_id("sia_pa.v1", HASH_LOGICO, (ARTEFATO,)),
        schema_id="sia_pa.v1",
        caminho="data/canonical/sia_pa.parquet",
        hash_logico=HASH_LOGICO,
        linhas=linhas,
        artifact_ids=(ARTEFATO,),
        origem_dados=OrigemDados.REAL,
        produzido_por="run_ingestao",
    )


def split_sintetico() -> SplitManifest:
    intervalos = tuple(
        IntervaloParticao(particao=particao, inicio=inicio, fim=fim)
        for particao, inicio, fim in PARTICOES_DO_PLANO
    )
    return SplitManifest(
        split_id="split_1",
        spec=SplitSpec(intervalos=intervalos),
        dataset_hash=HASH_LOGICO,
        linhas_por_particao=dict.fromkeys(Particao, 1),
        hash_por_particao=dict.fromkeys(Particao, HASH_LOGICO),
    )


def features_sinteticas() -> FeatureSpec:
    atributo = Atributo(nome="f_idade", schema_id="sia_pa.v1", coluna="idade", transformacao="id")
    return FeatureSpec(feature_set_id="fs_1", atributos=(atributo,))
