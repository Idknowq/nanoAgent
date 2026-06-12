---
name: node-repository
description: Diagnose Node.js repositories, package-manager failures, tests, builds, module resolution, and type checking. Use when Node project markers or JavaScript failures are present.
compatibility: Node.js tooling may be required for verification.
metadata:
  version: "1.0"
---

# Node.js Repository Diagnosis

- Inspect `package.json`, lockfiles, scripts, and relevant configuration.
- Use the package manager implied by the lockfile.
- Prefer declared scripts such as `test`, `lint`, and `build` over guessed commands.
- Separate dependency installation, module resolution, type checking, test, and build failures.
- Run the narrowest relevant script after a repair, then broaden verification when practical.
