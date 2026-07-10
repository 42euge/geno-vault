---
name: geno-vault-ws-init
description: >-
  Create a new dot-notation workspace — scaffolds the directory, clones repos,
  writes a colour-coded VS Code workspace file, fetches ticket context,
  and registers the workspace in the geno registry so the GUI shows it
  immediately. Works locally or on a remote host (--host).
allowed-tools: "Bash(geno-vault *)"
metadata:
  author: 42euge
  version: "0.3.0"
---

# geno-vault ws init

Full workspace creation from a single command.

```
geno-vault ws init <track.domain.workspace> \
  [--host <ssh-alias>]          # remote host (e.g. a dev workstation)
  [--repo <path-or-url>]        # repeat for each repo
  [--ticket <TICKET-KEY>]       # fetch context YAML
```

**Examples:**
```bash
# Local workspace with two repos + ticket context
geno-vault ws init crit.myproject.feature \
  --repo myorg/myrepo \
  --repo myorg/deploy-scripts \
  --ticket PROJ-123

# Remote workspace
geno-vault ws init crit.myproject.feature \
  --host devbox \
  --repo myorg/myrepo \
  --ticket PROJ-123
```

**What it does:**
1. `mkdir ~/code/<track>/<domain>/<workspace>.<quarter>/`
2. `git clone` each repo into it (git host resolved from `~/.geno/config.yaml`)
3. Writes `<workspace>.code-workspace` (deterministic accent colour, copilot off)
4. Writes `<ticket>.yaml` with ticket summary/status/url (provider from config)
5. Registers the `vscode` key in `~/.geno/workspace.json` → GUI `⎔ VS Code` button works immediately

**Configuration** (`~/.geno/config.yaml`):
```yaml
git:
  default_host: myforge
  hosts:
    myforge:
      base_url: https://git.example.com
      token_env: GIT_TOKEN
tickets:
  provider: github   # or: custom (set adapter_module path)
```
