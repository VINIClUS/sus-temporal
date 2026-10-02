import importlib
import inspect

import pytest

INTERFACES = [
    ("sustemporal.cli", "load_config", [("path", "Path")], "RunConfig"),
    (
        "sustemporal.acquisition.fetch",
        "fetch_source",
        [("request", "SourceRequest"), ("store", "Path")],
        "ArtifactObservation",
    ),
    (
        "sustemporal.acquisition.watch",
        "observe_updates",
        [("requests", "list[SourceRequest]"), ("store", "Path")],
        "list[ArtifactObservation]",
    ),
    (
        "sustemporal.ingest.sia_pa",
        "normalize_pa",
        [("artifact", "ArtifactVersion"), ("layout", "LayoutSpec"), ("out", "Path")],
        "DatasetRef",
    ),
    (
        "sustemporal.evaluation.labels",
        "label_pa",
        [("dataset", "DatasetRef"), ("codebook", "Path"), ("out", "Path")],
        "DatasetRef",
    ),
    (
        "sustemporal.ingest.cnes",
        "normalize_cnes",
        [("artifact", "ArtifactVersion"), ("layout", "LayoutSpec"), ("out", "Path")],
        "DatasetRef",
    ),
    (
        "sustemporal.ingest.sigtap",
        "normalize_sigtap",
        [("artifact", "ArtifactVersion"), ("layout", "LayoutSpec"), ("out", "Path")],
        "DatasetRef",
    ),
    (
        "sustemporal.reporting.report",
        "build_pilot_report",
        [("datasets", "list[DatasetRef]"), ("cohort", "CohortSpec"), ("out", "Path")],
        "EvaluationReport",
    ),
    (
        "sustemporal.temporal.selector",
        "select_snapshots",
        [("record", "ProductionRecord"), ("rule", "RuleSpec"), ("config", "RunConfig")],
        "SnapshotSet",
    ),
    (
        "sustemporal.rules.engine",
        "evaluate_rules",
        [
            ("dataset", "DatasetRef"),
            ("snapshots", "SnapshotSet"),
            ("rules", "list[RuleSpec]"),
            ("config", "RunConfig"),
            ("out", "Path"),
        ],
        "RunResult",
    ),
    (
        "sustemporal.explanation.explain",
        "explain",
        [("run", "RunResult"), ("row_id", "str")],
        "ExplanationBundle",
    ),
    (
        "sustemporal.explanation.counterfactual",
        "search_counterfactuals",
        [("bundle", "ExplanationBundle"), ("config", "RunConfig")],
        "CounterfactualSearchResult",
    ),
    (
        "sustemporal.evaluation.split",
        "build_splits",
        [("dataset", "DatasetRef"), ("cohort", "CohortSpec"), ("out", "Path")],
        "SplitManifest",
    ),
    (
        "sustemporal.evaluation.baselines",
        "fit_baseline",
        [
            ("split", "SplitManifest"),
            ("features", "FeatureSpec"),
            ("config", "RunConfig"),
            ("out", "Path"),
        ],
        "RunResult",
    ),
    (
        "sustemporal.evaluation.metrics",
        "evaluate_runs",
        [
            ("runs", "list[RunResult]"),
            ("labels", "DatasetRef"),
            ("split", "SplitManifest"),
            ("out", "Path"),
        ],
        "EvaluationReport",
    ),
    (
        "sustemporal.evaluation.annotation",
        "prepare_annotation_sample",
        [
            ("labels", "DatasetRef"),
            ("split", "SplitManifest"),
            ("config", "RunConfig"),
            ("out", "Path"),
        ],
        "AnnotationSample",
    ),
    (
        "sustemporal.evaluation.values",
        "summarize_values",
        [("run", "RunResult"), ("labels", "DatasetRef"), ("out", "Path")],
        "DatasetRef",
    ),
    (
        "sustemporal.reporting.reproduce",
        "reproduce",
        [("config", "RunConfig"), ("out", "Path")],
        "EvaluationReport",
    ),
]


@pytest.mark.parametrize(
    ("modulo", "funcao", "parametros", "retorno"), INTERFACES, ids=[i[1] for i in INTERFACES]
)
def test_interface_do_plano_mantem_assinatura(
    modulo: str, funcao: str, parametros: list[tuple[str, str]], retorno: str
) -> None:
    alvo = getattr(importlib.import_module(modulo), funcao)
    assinatura = inspect.signature(alvo)
    posicionais = [
        p for p in assinatura.parameters.values() if p.kind is not inspect.Parameter.KEYWORD_ONLY
    ]
    assert [(p.name, p.annotation) for p in posicionais] == parametros
    extras = [p for p in assinatura.parameters.values() if p.kind is inspect.Parameter.KEYWORD_ONLY]
    assert all(p.default is not inspect.Parameter.empty for p in extras)
    assert assinatura.return_annotation == retorno
