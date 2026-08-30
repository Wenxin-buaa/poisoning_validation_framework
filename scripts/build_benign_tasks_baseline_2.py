#!/usr/bin/env python3
"""Split benign pair tasks into baseline_2-style stepwise prompts.

This script converts benchmarks/benign_tasks/*.json into a parallel directory
benchmarks/benign_tasks_baseline_2/ with the same filenames. Each task entry is
expanded to include step_1 / step_2 prompts and artifact handoff hints.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "benchmarks" / "benign_tasks"
DST_DIR = ROOT / "benchmarks" / "benign_tasks_baseline_2"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true", help="Replace the output directory if it exists.")
    args = parser.parse_args()

    if DST_DIR.exists() and args.overwrite:
        shutil.rmtree(DST_DIR)
    DST_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "schema_version": "2026-08-27.benign_tasks_baseline_2_index.v1",
        "source_dir": rel(SRC_DIR),
        "output_dir": rel(DST_DIR),
        "split_strategy": "comma_half_split_v1",
        "files": [],
    }

    source_files = sorted(SRC_DIR.glob("*_tasks.json"))
    for src in source_files:
        data = json.loads(src.read_text(encoding="utf-8"))
        out = {
            "schema_version": "2026-08-27.benign_tasks_baseline_2_file.v1",
            "source_file": rel(src),
            "pack_id": data.get("pack_id"),
            "split_strategy": "comma_half_split_v1",
            "tasks": [],
        }
        tasks = data.get("tasks", [])
        for task in tasks:
            task_id = str(task["task_id"])
            inputs = dict(task.get("inputs") or {})
            prompt = str(task["task_prompt"])
            step_1_prompt, step_2_prompt = split_prompt(prompt)
            step_1_artifact = f"artifacts/{task_id}_step_1_output.md"
            step_2_artifact = f"artifacts/{task_id}_step_2_output.md"

            out["tasks"].append(
                {
                    "task_id": task_id,
                    "inputs": inputs,
                    "source_task_prompt": prompt,
                    "step_1": {
                        "task_id": f"{task_id}_step_1",
                        "task_prompt": step_1_prompt,
                        "inputs": inputs,
                        "expected_output_artifact": step_1_artifact,
                    },
                    "step_2": {
                        "task_id": f"{task_id}_step_2",
                        "task_prompt": step_2_prompt,
                        "inputs": inputs,
                        "expected_output_artifact": step_2_artifact,
                        "consumes_artifact": step_1_artifact,
                    },
                }
            )

        dst = DST_DIR / src.name
        dst.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["files"].append(
            {
                "source_file": rel(src),
                "output_file": rel(dst),
                "task_count": len(out["tasks"]),
            }
        )

    (DST_DIR / "index.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def split_prompt(prompt: str) -> tuple[str, str]:
    text = prompt.strip().rstrip(".")
    clauses = [normalize_clause(part, index) for index, part in enumerate(text.split(","))]
    clauses = [clause for clause in clauses if clause]
    if len(clauses) < 2:
        raise ValueError(f"Prompt does not contain enough comma-separated clauses: {prompt}")

    split_at = 2 if len(clauses) == 3 else max(1, len(clauses) // 2)
    if split_at >= len(clauses):
        split_at = len(clauses) - 1

    step_1_raw = join_clauses(clauses[:split_at])
    step_2_raw = join_clauses(clauses[split_at:])

    step_1 = sentence(step_1_raw)
    step_2 = sentence("Use the output from Step 1 to " + lowercase_first_letter(step_2_raw))
    return step_1, step_2


def normalize_clause(text: str, index: int) -> str:
    clause = text.strip()
    if index > 0:
        clause = re.sub(r"^(and|then)\s+", "", clause, flags=re.IGNORECASE)
    return clause.strip()


def join_clauses(clauses: list[str]) -> str:
    if len(clauses) == 1:
        return clauses[0].strip()
    if len(clauses) == 2:
        return f"{clauses[0].strip()}, {clauses[1].strip()}"
    return ", ".join(c.strip() for c in clauses[:-1]) + f", and {clauses[-1].strip()}"


def sentence(text: str) -> str:
    text = text.strip().rstrip(".")
    return text + "."


def lowercase_first_letter(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].lower() + text[1:]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
