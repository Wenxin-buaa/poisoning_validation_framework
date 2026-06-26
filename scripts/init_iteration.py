#!/usr/bin/env python3
import argparse
import json
import shutil
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK = Path(__file__).resolve().parents[1]
PACK_INDEX = FRAMEWORK / "benchmarks" / "clean_packs" / "pack_index.json"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def copy_skill(source, destination):
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iteration-id", required=True)
    parser.add_argument("--pack", required=True)
    parser.add_argument("--hook", required=True)
    parser.add_argument("--sink", required=True)
    parser.add_argument("--pair", required=True)
    args = parser.parse_args()

    index = load_json(PACK_INDEX)
    pack = index["packs"][args.pack]
    iteration_dir = FRAMEWORK / "benchmarks" / "iterations" / args.iteration_id
    clean_snapshot = iteration_dir / "clean_pack_snapshot"
    variant_dir = iteration_dir / "poisoned_pack_variant"
    poisoned_traces = iteration_dir / "poisoned_traces"

    clean_snapshot.mkdir(parents=True, exist_ok=True)
    variant_dir.mkdir(parents=True, exist_ok=True)
    poisoned_traces.mkdir(parents=True, exist_ok=True)

    for skill_name, source in pack["skills"].items():
        source_path = WORKSPACE_ROOT / source
        if not source_path.exists():
            raise FileNotFoundError(source)
        copy_skill(source_path, clean_snapshot / skill_name)
        copy_skill(source_path, variant_dir / skill_name)

    manifest = {
        "iteration_id": args.iteration_id,
        "pack_id": args.pack,
        "selected_hook_sink_pair": args.pair,
        "hook_skill": args.hook,
        "sink_skill": args.sink,
        "clean_snapshot": str(clean_snapshot.relative_to(WORKSPACE_ROOT)),
        "poisoned_pack_variant": str(variant_dir.relative_to(WORKSPACE_ROOT)),
        "poisoned_traces": str(poisoned_traces.relative_to(WORKSPACE_ROOT)),
        "pair_selection_analysis": str((iteration_dir / "pair_selection_analysis.json").relative_to(WORKSPACE_ROOT)),
        "attack_iteration": str((iteration_dir / "attack_iteration.json").relative_to(WORKSPACE_ROOT)),
        "notes": str((iteration_dir / "notes.md").relative_to(WORKSPACE_ROOT)),
        "clean_pack_mutated": False,
        "real_skill_dir_mutated": False
    }
    (iteration_dir / "iteration_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8"
    )
    (iteration_dir / "notes.md").touch()
    print(iteration_dir.relative_to(WORKSPACE_ROOT))


if __name__ == "__main__":
    main()
