---
name: node-repository
description: Investigate and repair Node.js repository failures involving package scripts, tests, builds, module resolution, or type checking. Activate when JavaScript or TypeScript tooling materially affects the task.
compatibility: Node.js tooling may be required for verification.
metadata:
  version: "2.0"
---

# Node.js Repository Repair

## Orient

- Read applicable repository instructions, the nearest `package.json`, lockfile, workspace
  configuration, and only the tool configuration relevant to the failure.
- Use the package manager and workspace layout indicated by the lockfile and repository scripts.
  Do not create or replace lockfiles unless dependency changes are required.
- Prefer declared scripts over guessed commands. Inspect a script before invoking it.

## Diagnose

- Reproduce the smallest relevant test, script, import, type-check, or build failure.
- Separate dependency installation, package-manager, module format, module resolution, transpilation,
  type checking, test-runner, and runtime failures before editing.
- Trace the failing behavior through source and tests. Check whether generated output, build
  artifacts, browser assumptions, or workspace boundaries are involved.

## Repair

- Preserve module format, package exports, supported runtimes, and public API behavior unless the
  task requires changing them.
- Avoid dependency upgrades, lockfile churn, script rewrites, and configuration changes without
  direct evidence.
- Do not weaken assertions, snapshots, lint rules, or type checking merely to pass verification.

## Verify

1. Re-run the focused failing command.
2. Run the nearest declared test, type-check, lint, or build script.
3. Broaden to the package or workspace level when practical.
4. Report environment or installation blockers separately from source-code results.
