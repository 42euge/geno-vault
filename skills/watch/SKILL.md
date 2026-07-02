---
name: geno-vault-watch
description: >-
  Auto-commit the registry whenever a surface changes it (reuses geno-pear's mtime-poll watch).
allowed-tools: "Bash(vault *)"
metadata:
  author: 42euge
  version: "0.1.0"
---

# vault/watch

```
vault watch [--apply]
```

Polls ~/.geno/workspace.json (geno-pear's mtime mechanism) and commits a snapshot on every change. `--apply` also re-pushes the registry to the surfaces, keeping iTerm and Chromium in lockstep with the registry.
