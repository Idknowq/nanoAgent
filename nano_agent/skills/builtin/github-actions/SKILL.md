---
name: github-actions
description: Diagnose GitHub Actions workflows, permissions, environment setup, caching, and repository commands. Use when workflow failures or files under .github/workflows are relevant.
compatibility: Local reproduction may require the repository's language tooling.
metadata:
  version: "1.0"
allowed-tools:
  - read_file
  - run_command
---

# GitHub Actions Diagnosis

- Read the relevant workflow and the project command it invokes.
- Check event filters, permissions, action versions, environment setup, caching, and paths.
- Reproduce the underlying command locally when possible before editing workflow YAML.
- Keep workflow permissions minimal and do not expose or print secrets.
- Validate YAML structure and the repository command affected by the change.
