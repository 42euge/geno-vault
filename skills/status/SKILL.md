---
name: geno-vault-status
description: >-
  Show the unified cross-surface registry (iterm + chrome per node) and the vault's latest commit.
allowed-tools: "Bash(vault *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# vault/status

```
vault status
```

Prints every object-notation node with its per-surface attachments (iterm cwd/tty, chrome group/tab count) and the vault git HEAD. The one-glance view of the whole workspace.
