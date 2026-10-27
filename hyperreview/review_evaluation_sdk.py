"""Explicit local MLflow GenAI evaluation of sealed reviewer artifacts.

No inference, judges, collection or GitHub writes. Only numeric witnesses and
opaque lineage reach the SDKs; source, rubrics and reviewer prose stay local.
"""

import argparse
import hashlib
import importlib.metadata
import math
from numbers import Real
import os
from pathlib import Path
import sys

from . import intake, review_evaluation
from .evaluation_delivery import (
    EvaluationDeliveryError, _check_sqlite_path_syntax, _load_client,
    _tracking_uri, _trusted_input_file, _trusted_path,
)
from .evaluation_report import EVIDENTLY_VERSION, MAX_OUTPUT_BYTES
from .storage import read_json, write_bundle


EXPERIMENT = "HyperReview controlled reviewer evaluation v1"


def _mean_matches(value, expected):
    # Native aggregate results may be NumPy scalars, unlike client readback.
    return (not isinstance(value, bool) and isinstance(value, Real)
            and math.isfinite(value) and abs(float(value) - expected) < 1e-12)


def _native_engine(comparison, *, database, artifacts_root, output_root):
    uri = _tracking_uri(database)
    os.environ.update(DO_NOT_TRACK="1", EVIDENTLY_DISABLE_TELEMETRY="1",
                      MLFLOW_REGISTRY_URI=uri, MLFLOW_ENABLE_ASYNC_TRACE_LOGGING="false")
    client = _load_client(uri)  # Exact SDK pin and local SQLite URI, before import.
    review_evaluation.require(importlib.metadata.version("evidently") == EVIDENTLY_VERSION,
                              "Controlled reports require Evidently 0.7.23")
    import mlflow
    import pandas as pd
    from evidently import Report
    from evidently.metrics import MeanValue
    from mlflow.entities import Feedback
    from mlflow.genai.scorers import scorer
    from mlflow.entities.trace_location import MlflowExperimentLocation

    review_evaluation.require(mlflow.active_run() is None, "Close the active MLflow run before evaluation")
    mlflow.set_registry_uri(uri)
    experiment = client.get_experiment_by_name(EXPERIMENT)
    if experiment is None:
        experiment_id = client.create_experiment(EXPERIMENT, artifact_location=artifacts_root.as_uri())
        experiment = client.get_experiment(experiment_id)
    review_evaluation.require(experiment.artifact_location == artifacts_root.as_uri(),
                              "MLflow experiment uses another artifact root")
    mlflow.set_experiment(experiment_id=experiment.experiment_id)
    mlflow.tracing.set_destination(MlflowExperimentLocation(experiment_id=experiment.experiment_id))

    @scorer(name="review_witnesses", aggregations=["mean"])
    def witnesses(outputs):
        return [Feedback(name=name, value=float(value)) for name, value in outputs.items() if value is not None]

    runs, reports = [], {}
    # Keep intake and explanation populations separate. Missing observations
    # remain missing; no single overall score or sample-size significance claim.
    for axis in sorted({row["axis"] for row in comparison["rows"]}):
        selected = [row for row in comparison["rows"] if row["axis"] == axis]
        frames = {}
        columns = [key for key in review_evaluation.METRICS
                   if any(row["outputs"][key] is not None for row in selected)]
        for variant in ("baseline", "candidate"):
            rows = [row for row in selected if row["variant"] == variant]
            data = [{"inputs": {key: value for key, value in row.items() if key != "outputs"},
                     "outputs": row["outputs"]} for row in rows]
            frames[variant] = pd.DataFrame([row["outputs"] for row in rows], columns=columns)
            with mlflow.start_run(run_name=f"{axis}-{variant}", tags={
                "hyperreview.suite_digest": comparison["suite_digest"],
                "hyperreview.metric_version": comparison["metric_version"],
                "hyperreview.assessor_type": comparison["assessor_type"],
                "hyperreview.semantic_assessment": "pending",
                "hyperreview.publication_gate": "false",
                "hyperreview.axis": axis, "hyperreview.variant": variant,
                "hyperreview.delivery_stage": "pending",
                "hyperreview.metric_code_sha256": review_evaluation.metric_code_digest(),
            }) as run:
                # Native MLflow API evaluates pre-generated outputs. There is
                # deliberately no predict_fn or built-in model judge here.
                evaluated = mlflow.genai.evaluate(data=data, scorers=[witnesses])
                for name in columns:
                    measured = [row["outputs"][name] for row in rows if row["outputs"][name] is not None]
                    if measured:
                        expected = sum(measured) / len(measured)
                        actual = evaluated.metrics.get(f"{name}/mean")
                        review_evaluation.require(_mean_matches(actual, expected),
                                                  "Native scorer result is missing or inconsistent")
                        recorded = client.get_run(run.info.run_id).data.metrics.get(f"{name}/mean")
                        review_evaluation.require(_mean_matches(recorded, expected),
                                                  "Native scorer metric readback failed")
                    mlflow.log_metric(f"{name}_measured_count", len(measured))
                mlflow.log_metric("case_count", len(rows))
                mlflow.log_metric("unpaired_case_count", len(comparison["coverage"][axis]["unpaired_cases"]))
                review_evaluation.require(bool(evaluated.metrics), "MLflow produced no witness metrics")
                runs.append({"axis": axis, "variant": variant, "run_id": run.info.run_id})
        snapshot = Report([MeanValue(column=key) for key in columns]).run(
            current_data=frames["candidate"], reference_data=frames["baseline"])
        for suffix, body in (("json", snapshot.json().encode()),
                             ("html", snapshot.get_html_str(as_iframe=False).encode())):
            review_evaluation.require(len(body) <= MAX_OUTPUT_BYTES, "Evidently report exceeds limit")
            reports[f"{axis}.{suffix}"] = body

    receipt = {"schema": "hyperreview.native-review-evaluation.v1", "runs": runs,
               "suite_digest": comparison["suite_digest"], "semantic_assessment": "pending",
               "publication_gate": False}
    bundle = write_bundle({**reports, "comparison.json": intake.encoded(comparison),
                           "receipt.json": intake.encoded(receipt)}, output_root)
    # Only regenerated, sanitized artifacts, never operator-provided HTML or prose.
    for run in runs:
        try:
            for name in (f"{run['axis']}.json", f"{run['axis']}.html", "comparison.json", "receipt.json"):
                client.log_artifact(run["run_id"], str(bundle / name), artifact_path="evaluation")
                received = Path(client.download_artifacts(run["run_id"], f"evaluation/{name}"))
                review_evaluation.require(not received.is_symlink() and received.is_file()
                                          and received.stat().st_size <= MAX_OUTPUT_BYTES
                                          and hashlib.sha256(received.read_bytes()).digest()
                                          == hashlib.sha256((bundle / name).read_bytes()).digest(),
                                          "Native evaluation artifact readback failed")
            recorded = client.get_run(run["run_id"])
            review_evaluation.require(recorded.info.status == "FINISHED" and bool(recorded.data.metrics),
                                      "Native evaluation run readback failed")
            client.set_tag(run["run_id"], "hyperreview.delivery_stage", "confirmed")
            review_evaluation.require(client.get_run(run["run_id"]).data.tags.get(
                "hyperreview.delivery_stage") == "confirmed", "Evaluation confirmation readback failed")
        except Exception:
            client.set_terminated(run["run_id"], status="FAILED")
            raise
    return {"report_path": str(bundle), **receipt}


def evaluate(suite, pairs, *, database, artifacts_root, output_root, engine=None):
    """Validate lineage before SDK access; each explicit call creates fresh runs."""
    comparison = review_evaluation.compare(suite, pairs)
    _check_sqlite_path_syntax(database)
    database = _trusted_path(database, directory=False, create_parent=True)
    review_evaluation.require(database.suffix in (".db", ".sqlite", ".sqlite3"), "Use a SQLite filename")
    artifacts_root = _trusted_path(artifacts_root, directory=True, create=True)
    output_root = _trusted_path(output_root, directory=True, create=True)
    return (engine or _native_engine)(comparison, database=database,
                                      artifacts_root=artifacts_root, output_root=output_root)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--pairs", required=True, type=Path)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--artifacts-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        suite = read_json(_trusted_input_file(args.suite))
        pairs = read_json(_trusted_input_file(args.pairs))
        result = evaluate(suite, pairs, database=args.database, artifacts_root=args.artifacts_root,
                          output_root=args.output_root)
    except (review_evaluation.ReviewEvaluationError, EvaluationDeliveryError):
        print("HyperReview: controlled evaluation rejected; check local lineage and paths", file=sys.stderr)
        return 2
    except Exception:
        print("HyperReview: native evaluation failed; partial local runs may remain", file=sys.stderr)
        return 1
    print(intake.encoded(result).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
