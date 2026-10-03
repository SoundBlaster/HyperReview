"""Controlled boundary fixtures and a human scorecard, without executing source."""

import hashlib
import json
from pathlib import Path
import time

from . import intake, model_contract
from .compiled_preview import PreviewError, compile_preview
from .storage import write_bundle


CASES = (
    {"id": "case-001", "title": "Added discovery responsibility",
     "before": "def discover():\n    return []\n", "after": "def discover():\n    return cache_candidates()\n",
     "before_hc": "Discovery#discovery\n", "after_hc": "Discovery#discovery\n  CacheCandidates#candidates\n",
     "identities": (("discovery", True, True), ("candidates", False, True)),
     "accepted": True, "grammar_valid": 1, "reference_valid": 1, "changes": 1,
     "question": "Which responsibility was added, and what remains unknown about its behavior?",
     "answer": "#candidates was added beneath #discovery. The tree does not establish its algorithm or runtime behavior."},
    {"id": "case-002", "title": "Unsupported graph syntax",
     "before": "def discover():\n    return []\n", "after": "def discover():\n    return cache_candidates()\n",
     "before_hc": "Discovery#discovery\n", "after_hc": "Discovery#discovery -> CacheCandidates#candidates\n",
     "identities": (("discovery", True, True), ("candidates", False, True)),
     "accepted": False, "grammar_valid": 0, "reference_valid": 0, "changes": None,
     "question": "Can the proposed graph be presented as validated core Hypercode? Why?",
     "answer": "No: the arrow is outside core .hc grammar. The compiler must reject it; names cannot define new graph operators."},
    {"id": "case-003", "title": "Identity does not match the projection",
     "before": "def discover():\n    return []\n", "after": "def discover():\n    return cache_candidates()\n",
     "before_hc": "Discovery#discovery\n", "after_hc": "Discovery#renamed\n",
     "identities": (("discovery", True, True),),
     "accepted": False, "grammar_valid": 1, "reference_valid": 0, "changes": None,
     "question": "Does the identity map establish continuity with the after projection?",
     "answer": "No: #renamed appears in after .hc but the map refers to #discovery. Grammar validity alone does not establish reference integrity."},
    {"id": "case-004", "title": "Invented before baseline",
     "before": None, "after": "def approve(record):\n    return record.project_author\n",
     "before_hc": "Approval#approval\n", "after_hc": "Approval#approval\n",
     "identities": (("approval", False, True),),
     "accepted": False, "grammar_valid": 1, "reference_valid": 0, "changes": None,
     "question": "What supports the claimed earlier responsibility?",
     "answer": "Nothing supplied. An after-only source cannot support a populated before projection; it must be rejected rather than assumed unchanged."},
    {"id": "case-005", "title": "Implementation rename, stable responsibility",
     "before": "class CandidateFinder:\n    pass\n", "after": "class CacheScanner:\n    pass\n",
     "before_hc": "Discovery#discovery\n", "after_hc": "Discovery#discovery\n",
     "identities": (("discovery", True, True),),
     "accepted": True, "grammar_valid": 1, "reference_valid": 1, "changes": 0,
     "question": "Does a type rename necessarily add or remove an architectural responsibility?",
     "answer": "No. The controlled identity decision keeps #discovery stable. Real correspondence still needs review; equal trees do not prove equal behavior."},
    {"id": "case-006", "title": "Behavioral bypass hidden by unchanged composition",
     "before": "def cleanup(approved):\n    if not approved:\n        return False\n    return trash()\n",
     "after": "def cleanup(approved, fast):\n    if fast:\n        return trash()\n    if not approved:\n        return False\n    return trash()\n",
     "before_hc": "Cleanup#cleanup\n  UserApproval#approval\n  TrashOperation#trash\n",
     "after_hc": "Cleanup#cleanup\n  UserApproval#approval\n  TrashOperation#trash\n",
     "identities": (("cleanup", True, True), ("approval", True, True), ("trash", True, True)),
     "accepted": True, "grammar_valid": 1, "reference_valid": 1, "changes": 0,
     "question": "Does an unchanged structural diff establish preserved approval? Point to any bypass in the supplied source.",
     "answer": "No. In the illustrated source, fast invokes trash before the approval guard. This is a static source observation under the fixture's assumptions, not observed execution."},
)


def _source(side, content, revision):
    return {"side": side, "revision": revision, "path": "fixture/subject.py", "content": content,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(), "line_start": 1,
            "line_end": content.count("\n"), "trust": "untrusted_source_data"}


def _request(case):
    # Synthetic revision IDs are only inputs to the boundary fixture. They are
    # never presented as real Git commits or used to construct GitHub links.
    base = hashlib.sha256((case["id"] + "before").encode()).hexdigest()[:40]
    head = hashlib.sha256((case["id"] + "after").encode()).hexdigest()[:40]
    sources = []
    if case["before"] is not None:
        sources.append(_source("before", case["before"], base))
    sources.append(_source("after", case["after"], head))
    pack = {"schema": intake.SCHEMA, "stage": "evidence_collected", "repository": "0al-spec/SpecGraph",
            "pr": 1, "author": intake.AUTHOR, "authenticated_account": intake.AUTHOR,
            "base_repo": "0al-spec/SpecGraph", "head_repo": "0al-spec/SpecGraph",
            "state": "open", "draft": False, "base_sha": base, "merge_base_sha": base, "head_sha": head,
            "files": [{"before_path": "fixture/subject.py" if case["before"] is not None else None,
                       "after_path": "fixture/subject.py", "sources": sources, "omissions": []}]}
    pack["evidence_digest"] = intake.digest(pack)
    return model_contract.prepare_request(pack)


def _result(case, request):
    before = [source["id"] for source in request["sources"] if source["side"] == "before"]
    after = [source["id"] for source in request["sources"] if source["side"] == "after"]
    return {"schema": model_contract.RESULT_SCHEMA, "request_digest": request["request_digest"],
            "before_hc": case["before_hc"], "after_hc": case["after_hc"],
            "identity_map": [{"architecture_id": "#" + identifier,
                              "before_refs": before if has_before else [],
                              "after_refs": after if has_after else [],
                              "reason": "Controlled fixture mapping; not a model-generated judgment."}
                             for identifier, has_before, has_after in case["identities"]],
            "claims": [], "summary": "Controlled boundary fixture; inspect code separately for behavior.",
            "limitations": ["Synthetic source and revisions; no GitHub evidence or runtime execution.",
                            "Manually authored projection; not a measured model generation."]}


def run_pilot(compiler, compiler_sha256, output_root):
    """Run six deterministic boundary cases and prepare an unfilled human scorecard."""
    assessments, details = [], []
    dataset_digest = intake.digest({"version": "controlled-boundaries-v1", "cases": CASES})
    question_lines = ["# Controlled boundary cases — reviewer worksheet\n",
                      "These are synthetic fixtures, not real PRs or a completed three-condition study. "
                      "Projections were authored for boundary tests, not generated by an LLM. "
                      "Answer keys are in a separate file. Human accuracy and review time are unmeasured.\n"]
    scorecard = ["case_id,reviewer_id,condition,order,answer,correct,missed_violation,review_seconds,confidence\n"]
    answers = ["# Controlled fixture answer key\n", "Do not open before recording your answers.\n"]
    for case in CASES:
        request = _request(case)
        result = _result(case, request)
        started = time.monotonic()
        accepted = False
        observed_changes = None
        failure = None
        try:
            compiled = compile_preview(request, result, compiler=Path(compiler),
                                       compiler_sha256=compiler_sha256, timeout_seconds=60)
            accepted = True
            observed_changes = compiled["receipt"]["change_count"]
        except PreviewError as error:
            failure = str(error)  # Application-owned diagnostics, never compiler text.
        match = accepted == case["accepted"] and (not accepted or observed_changes == case["changes"])
        # Passing a rejection fixture is not a positive grammar/reference result.
        # Rejection class is checked against the controlled expected diagnostic;
        # an unrelated transport/binary failure is never counted as a passing test.
        if not accepted:
            expected_failure = {"case-002": "Hypercode compiler command failed",
                                "case-003": "Hypercode IR IDs do not match the model identity map",
                                "case-004": "Before-side identity references do not match emitted IR"}.get(case["id"])
            match = match and expected_failure is not None and failure == expected_failure
        assessments.append({"case_id": case["id"],
                            "projection_grammar_valid": case["grammar_valid"] if match else 0,
                            "projection_reference_valid": case["reference_valid"] if match else 0,
                            "validator_expected_outcome_match": int(match),
                            "structural_change_count": observed_changes, "omissions": len(request["omissions"]),
                            "elapsed_ms": int((time.monotonic() - started) * 1000)})
        details.append({"case_id": case["id"], "accepted": accepted, "expected_acceptance": case["accepted"],
                        "failure": failure, "request_digest": request["request_digest"],
                        "result_digest": intake.digest(result)})
        question_lines.extend([f"## {case['id']} — {case['title']}\n",
                               "### Before source (not executed)\n```python\n" + (case["before"] or "") + "```\n",
                               "### After source (not executed)\n```python\n" + case["after"] + "```\n",
                               "### Proposed before .hc\n```hc\n" + case["before_hc"] + "```\n",
                               "### Proposed after .hc\n```hc\n" + case["after_hc"] + "```\n",
                               f"Question: {case['question']}\n"])
        scorecard.append(f"{case['id']},,,,,,,,\n")
        answers.extend([f"## {case['id']}\n", case["answer"] + "\n"])
    assessment = {"schema": "hyperreview.evaluation.v1", "dataset_digest": dataset_digest,
                  "metric_definition_version": "boundary-v1", "assessor_type": "deterministic",
                  "records": assessments}
    destination = write_bundle({"assessments.json": intake.encoded(assessment),
                                "boundary-receipts.json": intake.encoded(details),
                                "dataset.json": intake.encoded({"version": "controlled-boundaries-v1",
                                                                "dataset_digest": dataset_digest, "cases": CASES}),
                                "reviewer-worksheet.md": "\n".join(question_lines).encode(),
                                "scorecard.csv": "".join(scorecard).encode(),
                                "answer-key.md": "\n".join(answers).encode()}, Path(output_root))
    return {"destination": destination, "assessment": assessment,
            "all_expected_outcomes_matched": all(row["validator_expected_outcome_match"] for row in assessments)}
