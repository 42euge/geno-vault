---
name: geno-vault-sync
description: >-
  Pull every surface (iTerm via tt, Chromium via surf) into the shared registry and git-commit a snapshot.
allowed-tools: "Bash(vault *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# vault/sync

```
vault sync
```

Runs `tt iterm reg pull` + `surf reg pull` to refresh ~/.geno/workspace.json, then snapshots it into the vault git repo (~/.geno/vault/) as one commit — a versioned point-in-time of the whole cross-surface workspace.
