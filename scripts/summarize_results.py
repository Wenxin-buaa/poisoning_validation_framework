#!/usr/bin/env python3
import json
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    judge_dir = FRAMEWORK / "benchmarks" / "judge_results"
    exploit_dir = FRAMEWORK / "benchmarks" / "exploits"
    verdicts = []
    exploits = []

    for path in sorted(judge_dir.glob("**/*.json")):
        try:
            verdicts.append(load_json(path))
        except json.JSONDecodeError:
            continue
    for path in sorted(exploit_dir.glob("**/*.json")):
        try:
            exploits.append(load_json(path))
        except json.JSONDecodeError:
            continue

    summary = {
        "verdict_count": len(verdicts),
        "success_count": sum(1 for item in verdicts if item.get("verdict") == "success"),
        "failure_count": sum(1 for item in verdicts if item.get("verdict") == "failure"),
        "inconclusive_count": sum(1 for item in verdicts if item.get("verdict") == "inconclusive"),
        "exploit_count": len(exploits),
        "successful_pairs": sorted({
            item.get("selected_hook_sink_pair")
            for item in exploits
            if item.get("selected_hook_sink_pair")
        })
    }
    out = FRAMEWORK / "benchmarks" / "result_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
