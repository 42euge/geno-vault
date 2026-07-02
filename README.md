# geno-vault

Persistence + sync conductor for the geno **object-notation registry** — the `vault` CLI.

Ties [geno-tt](https://github.com/42euge/geno-tt) (iTerm) and
[geno-surf](https://github.com/42euge/geno-surf) (Chromium) together through one
shared registry (`~/.geno/workspace.json`): pull every surface's state in, push
it back out, git-version every change, and watch for changes (reusing
[geno-pear](https://github.com/42euge/geno-pear)'s mtime-poll mechanism).

## Install
```bash
pipx install git+https://github.com/42euge/geno-vault.git
```

## Usage
```bash
vault status         # unified cross-surface view + vault HEAD
vault sync           # pull tt + surf into the registry, commit a snapshot
vault apply          # push the registry out to both surfaces
vault watch --apply  # auto-commit on change, re-apply to surfaces
vault log            # registry git history
```

Dependency-free (stdlib + git). See [GENO.md](GENO.md).
