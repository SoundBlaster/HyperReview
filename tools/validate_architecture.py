#!/usr/bin/env python3
"""Validate the desired HyperReview architecture with the external Hypercode CLI."""

import argparse
import itertools
import json
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PROFILES = [("default", ())] + [
    (f"{backend}-{mode}", (f"backend={backend}", f"mode={mode}"))
    for backend, mode in itertools.product(
        ("codex", "lmstudio", "ollama"), ("preview", "publish")
    )
]


def run(cli, *args, expected=0):
    result = subprocess.run(
        [str(cli), *map(str, args)], capture_output=True, text=True, timeout=60
    )
    if result.returncode != expected:
        raise RuntimeError(
            f"Hypercode {args[0]} returned {result.returncode}, expected {expected}"
            f"\n{result.stdout}\n{result.stderr}"
        )
    return result


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hypercode", required=True, type=Path)
    parser.add_argument("--artifacts", type=Path, default=ROOT / ".artifacts/hypercode")
    options = parser.parse_args()
    cli = options.hypercode.resolve()
    require(cli.is_file(), f"Hypercode executable does not exist: {cli}")
    output = options.artifacts.resolve()
    output.mkdir(parents=True, exist_ok=True)
    hc = ROOT / "architecture/reviewer.hc"
    hcs = ROOT / "architecture/reviewer.hcs"

    parsed = run(cli, "parse", hc)
    (output / "parse.txt").write_text(parsed.stdout)
    ids = re.findall(r"#([a-z][a-z0-9-]*)", hc.read_text())
    require(len(ids) == len(set(ids)), "Duplicate architecture ID")
    selectors = set(re.findall(r"'#([^']+)'", hcs.read_text()))
    require(selectors <= set(ids), f"Unknown ID selectors: {selectors - set(ids)}")

    with tempfile.TemporaryDirectory(prefix="hyperreview-validation-") as folder:
        invalid = Path(folder) / "invalid-concurrency.hcs"
        original = hcs.read_text()
        needle = "  concurrency: 1\n"
        require(original.count(needle) == 1, "Expected exactly one baseline concurrency value")
        invalid.write_text(original.replace(needle, "  concurrency: 2\n", 1))
        for name, profile in PROFILES:
            contexts = [value for context in profile for value in ("--ctx", context)]
            run(cli, "validate", hc, "--hcs", hcs, *contexts)
            emitted = run(cli, "emit", hc, "--hcs", hcs, *contexts, "--ir-version", "2")
            json.loads(emitted.stdout)
            (output / f"{name}.ir.json").write_text(emitted.stdout)
            rejected = subprocess.run(
                [str(cli), "validate", str(hc), "--hcs", str(invalid), *contexts],
                capture_output=True, text=True, timeout=60,
            )
            require(
                rejected.returncode != 0 and "HC2104" in rejected.stdout + rejected.stderr,
                f"{name}: invalid concurrency was not rejected with HC2104",
            )
            print(f"PASS {name}: validate, IR v2, invalid concurrency rejection")

    changed = run(
        cli, "diff", output / "lmstudio-preview.ir.json",
        output / "ollama-preview.ir.json", "--format", "json", expected=1,
    )
    json.loads(changed.stdout)
    (output / "backend.diff.json").write_text(changed.stdout)
    run(cli, "diff", output / "default.ir.json", output / "default.ir.json", expected=0)
    print(f"PASS parse, {len(ids)} unique IDs, selectors, changed and identical IR diffs")
    print(f"Artifacts: {output}")


if __name__ == "__main__":
    main()
