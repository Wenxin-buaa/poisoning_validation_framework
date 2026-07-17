#!/usr/bin/env python3
import json
from pathlib import Path

FRAMEWORK = Path(__file__).resolve().parents[1]


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    judge_dir = FRAMEWORK / "benchmarks" / "judge_results"
    exploit_dir = FRAMEWORK / "benchmarks" / "exploits"
    runs_dir = FRAMEWORK / "benchmarks" / "runs"
    verdicts = []
    exploits = []

    for path in sorted(judge_dir.glob("**/*.json")):
        try:
            verdicts.append(load_json(path))
        except json.JSONDecodeError:
            continue
    for path in sorted(runs_dir.glob("**/variants/*/sink_only/verdict.json")):
        try:
            verdicts.append(load_json(path))
        except json.JSONDecodeError:
            continue
    for path in sorted(runs_dir.glob("**/variants/*/coordinated/loop_*/verdict.json")):
        try:
            verdicts.append(load_json(path))
        except json.JSONDecodeError:
            continue
    for path in sorted(exploit_dir.glob("**/*.json")):
        try:
            exploits.append(load_json(path))
        except json.JSONDecodeError:
            continue
    for path in sorted(runs_dir.glob("**/exploits/*.json")):
        try:
            exploits.append(load_json(path))
        except json.JSONDecodeError:
            continue

    success_count = 0
    failure_count = 0
    inconclusive_count = 0
    routed_to_d4_count = 0
    successful_variants = []

    for item in verdicts:
        if isinstance(item.get("variant_verdicts"), list):
            for variant in item["variant_verdicts"]:
                verdict = variant.get("verdict")
                if verdict == "success":
                    success_count += 1
                    if variant.get("variant_id"):
                        successful_variants.append(variant["variant_id"])
                elif verdict == "failure":
                    failure_count += 1
                elif verdict == "inconclusive":
                    inconclusive_count += 1
                if variant.get("route_to_d4"):
                    routed_to_d4_count += 1
        else:
            verdict = item.get("verdict")
            if verdict == "success":
                success_count += 1
                if item.get("variant_id"):
                    successful_variants.append(item["variant_id"])
            elif verdict == "failure":
                failure_count += 1
            elif verdict == "inconclusive":
                inconclusive_count += 1
            if item.get("feedback", {}).get("recommended_next_stage") in {"D4", "D4_INITIAL", "D4_REVISION"}:
                routed_to_d4_count += 1

    summary = {
        "verdict_count": len(verdicts),
        "success_count": success_count,
        "failure_count": failure_count,
        "inconclusive_count": inconclusive_count,
        "routed_to_d4_count": routed_to_d4_count,
        "exploit_count": len(exploits),
        "successful_variants": sorted(set(successful_variants)),
        "successful_pairs": sorted({
            item.get("selected_hook_sink_pair")
            for item in exploits
            if item.get("selected_hook_sink_pair")
        }),
        "single_skill_exploits": sorted({
            item.get("source", {}).get("variant_id") or item.get("variant_id")
            for item in exploits
            if item.get("exploit_type") in {"single_skill", "sink_only"}
            and (item.get("source", {}).get("variant_id") or item.get("variant_id"))
        }),
    }
    out = FRAMEWORK / "benchmarks" / "result_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
