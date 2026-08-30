#!/usr/bin/env python3
"""Build a baseline_2 step-plan JSON from benign_tasks_baseline_2/."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "benchmarks" / "benign_tasks_baseline_2"
OUT_FILE = SRC_DIR / "step_plan.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SRC_DIR)
    parser.add_argument("--output-file", type=Path, default=OUT_FILE)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    output_file = args.output_file.resolve()
    if output_file.exists() and not args.overwrite:
        raise FileExistsError(f"{output_file} exists; pass --overwrite to replace it")

    variants: dict[str, Any] = {}
    files = sorted(source_dir.glob("*_tasks.json"))
    for src in files:
        data = json.loads(src.read_text(encoding="utf-8"))
        pack_id = str(data.get("pack_id") or src.stem.replace("_tasks", ""))
        tasks = data.get("tasks") or []
        if len(tasks) != 1:
            raise ValueError(f"{src} must contain exactly one task")
        task = tasks[0]
        step_1 = task["step_1"]
        step_2 = task["step_2"]
        variant_entry = {
            "source_file": rel(src),
            "pack_id": pack_id,
            "task_id": task.get("task_id"),
            "inputs": task.get("inputs") or {},
            "source_task_prompt": task.get("source_task_prompt"),
            "sink_only": {"step_1": step_1, "step_2": step_2},
            "coordinated": {"step_1": step_1, "step_2": step_2},
        }
        variants[pack_id] = variant_entry

    plan = {
        "schema_version": "2026-08-27.benign_tasks_baseline_2_step_plan.v1",
        "baseline": "baseline_2",
        "source_dir": rel(source_dir),
        "output_file": rel(output_file),
        "step_plan_shape": "variants.<source_variant_id>.{sink_only|coordinated}.step_1/step_2",
        "variants": variants,
        "source_variants": variants,
    }
    output_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
