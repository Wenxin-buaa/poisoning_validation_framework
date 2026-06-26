# Execution Modes

The framework uses two Target Agent execution modes.

## Benign Baseline

Clean pack only.

Purpose:

- verify the original task still works
- collect baseline trace
- collect `candidate_workflow_pairs` from three task prompts

## Poisoned Rerun

Poisoned skill plus the other benign skills in the same pack.

Purpose:

- rerun the same task prompts used in the benign baseline
- record whether the expected payload appears
- provide execution evidence for Judge Agent

## Required Trace Fields

Both modes should record:

- `run_id`
- `mode`
- `pack_id`
- `pair`
- `task_prompt`
- `skill_sequence`
- `skill_calls`
- `local_actions`
- `artifacts_read`
- `artifacts_written`
- `artifact_existence_checks`
- `flow_edges`
- `payload_observations`
- `task_completed`
