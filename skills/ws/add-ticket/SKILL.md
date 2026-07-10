---
name: geno-vault-ws-add-ticket
description: >-
  Fetch a ticket and write its context YAML into an existing workspace.
allowed-tools: "Bash(geno-vault *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# geno-vault ws add-ticket

Add a ticket context file to an existing workspace.

```
geno-vault ws add-ticket <track.domain.workspace> \
  --ticket <TICKET-KEY> \
  [--host <ssh-alias>]
```

**Example:**
```bash
geno-vault ws add-ticket crit.myproject.feature --ticket PROJ-456
```

Writes `proj-456.yaml` into the workspace directory with key, summary, status, and URL.
Ticket provider is configured in `~/.geno/config.yaml` → `tickets.provider`.
