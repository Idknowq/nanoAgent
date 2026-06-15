---
name: github-actions
description: Investigate and repair GitHub Actions workflow failures involving triggers, permissions, setup, matrices, caching, paths, or invoked repository commands. Activate only when workflow behavior is part of the task.
compatibility: Local reproduction may require the repository's language tooling.
metadata:
  version: "2.0"
allowed-tools:
  - read_file
  - run_command
---

# GitHub Actions Repair

## Diagnose

- Read the failing job and the repository script or command it invokes. A CI symptom may originate
  in project code or setup rather than workflow YAML.
- Trace `needs`, conditions, matrix values, working directories, environment variables, outputs,
  artifacts, and reusable workflow inputs through the failing path.
- Check event filters, token permissions, action references, runtime setup, cache keys, path
  assumptions, and shell/platform differences only when relevant to the observed failure.
- Reproduce the underlying repository command locally when possible. Do not claim hosted-runner
  behavior was reproduced if only the project command was tested.

## Repair

- Make the smallest workflow or source change that fixes the identified cause.
- Keep permissions least-privileged. Never print, synthesize, or commit secrets.
- Avoid unrelated action-version upgrades, formatting churn, matrix expansion, and cache redesign.
- Preserve intended trigger coverage and required checks unless the task explicitly changes them.

## Verify

- Validate the edited YAML structure through available project tooling or careful structural
  review.
- Run the affected repository command locally when possible.
- Re-read the complete changed job to verify indentation, expression syntax, data flow, and paths.
- State what still requires a hosted GitHub Actions run.
