#!/usr/bin/env python3
"""Summarize baseline_5 step outcomes for coordinated-success variants."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "benchmarks" / "runs"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def collect(pack: str, experiment: str) -> list[dict]:
    source_root = RUNS / pack / "experiments" / experiment
    rows = []
    for baseline_root in sorted(source_root.parent.glob(f"{experiment}_baseline_5_*")):
        for verdict_path in sorted(baseline_root.glob("variants/*/coordinated/loop_*/session/verdict.json")):
            verdict = load(verdict_path)
            rows.append(
                {
                    "model": baseline_root.name.removeprefix(f"{experiment}_baseline_5_"),
                    "variant_id": verdict.get("variant_id", verdict_path.parents[3].name),
                    "verdict": verdict.get("verdict", "missing"),
                    "step_1": (verdict.get("step_1") or {}).get("verdict", "missing"),
                    "step_2": (verdict.get("step_2") or {}).get("verdict", "missing"),
                    "summary_injected": bool(verdict.get("step_2_trace_summary_injected")),
                    "result_path": str(verdict_path),
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    args = parser.parse_args()

    rows = collect(args.pack, args.experiment_id)
    counts = Counter(row["verdict"] for row in rows)
    injected = sum(row["summary_injected"] for row in rows)
    print(f"pack: {args.pack}")
    print(f"source_experiment: {args.experiment_id}")
    print(f"rows: {len(rows)}")
    print(f"overall: {dict(sorted(counts.items()))}")
    print(f"summary_injected: {injected}/{len(rows)}")
    if args.format == "tsv":
        print("model\tvariant_id\tverdict\tstep_1\tstep_2\tsummary_injected\tresult_path")
        for row in rows:
            print(
                "\t".join(
                    str(row[key])
                    for key in ("model", "variant_id", "verdict", "step_1", "step_2", "summary_injected", "result_path")
                )
            )
    else:
        print("\n| Model | Variant | Overall | Step 1 | Step 2 | Summary injected |")
        print("| --- | --- | --- | --- | --- | --- |")
        for row in rows:
            print(
                f"| {row['model']} | {row['variant_id']} | {row['verdict']} | "
                f"{row['step_1']} | {row['step_2']} | {row['summary_injected']} |"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
