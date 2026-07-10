---
name: geno-vault-ws-open
description: >-
  Open a registered workspace in VS Code (local or remote via SSH).
  Uses the vscode key from the geno registry.
allowed-tools: "Bash(geno-vault *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# geno-vault ws open

Open a workspace in VS Code using the registered path.

```
geno-vault ws open <track.domain.workspace>
```

**Example:**
```bash
geno-vault ws open crit.myproject.feature
# → runs: code --remote ssh-remote+devbox /path/to/feature.code-workspace
```

Reads the `vscode.workspace` and `vscode.host` keys from `~/.geno/workspace.json`.
Equivalent to clicking the `⎔ VS Code` button in the vault GUI.
