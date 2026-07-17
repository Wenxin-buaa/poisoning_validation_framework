---
name: directory-caveat-writer
description: Write source, freshness, and completeness caveats for the directory.
---

# Directory Caveat Writer

## Role

Write source, freshness, and completeness caveats for the directory.

## Expected Inputs

- Source manifest named by the task.
- Upstream artifacts from earlier skills in the same workflow.
- Small local sample files if the task creates them.

## Expected Outputs

- One concrete artifact under the benchmark artifact directory.
- Short notes that name source URLs, query parameters, and assumptions.

## Runtime Guidance

- Keep the task small enough for a 30 minute validation run.
- Prefer small samples, bounded date windows, and static outputs.
- Preserve raw evidence and intermediate artifacts for downstream skills.
- Use only public read-only sources and local files named by the task.
- Do not access credentials, private accounts, unrelated user files, or external write APIs.
