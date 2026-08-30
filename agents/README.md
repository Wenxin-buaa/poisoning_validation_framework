# Agent Prompt Usage

This framework is a staged skill-pair poisoning generation pipeline. The run unit
is a preselected upstream/downstream skill pair, and the workflow keeps the same
sink-first escalation shape while allowing the artifact to be constructed rather
than inherited from a natural clean-pack intermediate.

The framework first discovers benign workflows, extracts candidate sinks, adapts Skill-Inject-style obvious injection examples into safe local benchmark payloads, builds a sink-only variant, and escalates to hook-sink only when sink-only fails.

## Terminology

* `sink_skill`: the skill where the payload is finally triggered or materialized.
* `upstream_skill`: a Stage B candidate observed before the sink in a benign workflow.
* `hook_skill`: the selected upstream skill after Stage D4 chooses and modifies it.
* `hook-sink`: the Stage D4/D5/D6 coordinated variant type.
* `coordinated`: the neutral directory/category name for hook-sink loop artifacts.

## Data Dependency Chain

1. **Stage A, Target Agent benign pair execution**
   - Input: `benchmarks/benign_tasks/<pack_id>_tasks.json` + `benchmarks/clean_packs/<pack_id>/`.
   - Output: `benchmarks/benign_runs/<pack_id>/traces/`.
   - Purpose: determine whether the pair forms a stable workflow and record skill calls plus artifact/context/state flow.

2. **Stage B, Target Agent pair trace normalization**
   - Input: `benchmarks/benign_runs/<pack_id>/traces/`.
   - Output: `benchmarks/benign_runs/<pack_id>/candidate_workflow_pairs.json`.
   - Purpose: normalize benign pair traces into pair metadata and preserve observed upstream/downstream runtime context for later stages. The historical filename is retained for compatibility.

3. **Stage C, Attack Agent payload intent selection**
   - Input: pair metadata + benign traces + `data/obvious_inject.json` examples.
   - Output: `benchmarks/iterations/<iteration_id>/payload_selections.json`.
   - Purpose: assign the full payload pool to each downstream skill in the pair.

4. **Stage D1, Attack Agent sink-only construction**
   - Input: Stage C payload adaptation + clean pack.
   - Output: `sink_only_variant/`, `sink_only_attack_iteration.json`, and compatibility copies under `poisoned_pack_variant/` and `attack_iteration.json`.

5. **Stage D2, Target Agent sink-only execution**
   - Input: same benign tasks + `sink_only_variant/`.
   - Output: `sink_only_traces/`.

6. **Stage D3, Judge Agent sink-only judge**
   - Input: `sink_only_attack_iteration.json` + `sink_only_traces/`.
   - Output: `judge_results/<iteration_id>_sink_only_verdict.json` and, if successful, `exploits/<iteration_id>_single_skill_exploit.json`.
   - If sink-only succeeds, stop the loop.

7. **Stage D4, Attack Agent hook-sink construction**
   - Used only if D3 fails or is inconclusive.
   - Input: sink-only failure feedback, Stage C record, Stage B upstream candidates, clean pack.
   - Purpose: choose one observed `upstream_skill` as `hook_skill`, then construct the hook-sink dependency.
   - Output: `hook_sink_variant/`, `hook_sink_attack_iteration.json`, and compatibility copies under `poisoned_pack_variant/` and `attack_iteration.json`.

8. **Stage D5, Target Agent hook-sink execution**
   - Input: same benign tasks + `hook_sink_variant/`.
   - Output: `hook_sink_traces/`.

9. **Stage D6, Judge Agent hook-sink judge**
   - Input: `hook_sink_attack_iteration.json` + `hook_sink_traces/` + sink-only verdict.
   - Output: `judge_results/<iteration_id>_hook_sink_verdict.json` and, if successful, `exploits/<iteration_id>_hook_sink_exploit.json`.

10. **Stage D7, Attack Agent revision after hook-sink failure**
    - Used only if D6 fails or is inconclusive and the maximum iteration count has not been reached.
    - Output: revised hook-sink variant under a new revision id.

## Payload Source Policy

Skill-Inject obvious injection data is used only as:

* payload intent examples;
* rewriting style examples;
* examples of instruction placement.

The framework must not implement harmful real-world effects from those examples. Every payload must be converted into a safe, local, inert benchmark effect under the iteration artifact directory.

## Path Convention

Workspace root:

```text
/Users/wuwenxin/Desktop/lab
```

Framework root:

```text
pair_poisoning_validation_framework
```

Runtime outputs stay under `pair_poisoning_validation_framework/`.

Benign baseline outputs live under `benchmarks/benign_runs/<pack_id>/` and are reused across iterations. Iteration outputs live under `benchmarks/iterations/<iteration_id>/`.
