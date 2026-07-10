---
name: geno-vault-ws-add-repo
description: >-
  Clone a new repo into an existing dot-notation workspace and update the
  VS Code workspace file. Registers the change in the geno registry.
allowed-tools: "Bash(geno-vault *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# geno-vault ws add-repo

Add a repo to an existing workspace after `geno-vault ws init`.

```
geno-vault ws add-repo <track.domain.workspace> \
  --repo <path-or-url> \
  [--host <ssh-alias>]
```

**Example:**
```bash
geno-vault ws add-repo crit.myproject.feature \
  --repo myorg/another-repo \
  --host devbox
```

Clones the repo, regenerates the `.code-workspace` with all repos, and updates the registry.
