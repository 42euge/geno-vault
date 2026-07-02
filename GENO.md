# geno-vault — sync conductor for the object-notation registry

`geno-vault` is the `vault` CLI: the persistence + sync hub that ties
[geno-tt](https://github.com/42euge/geno-tt) (iTerm) and
[geno-surf](https://github.com/42euge/geno-surf) (Chromium) together through one
shared **object-notation registry**.

## The registry

`~/.geno/workspace.json` — the source of truth. Each node is keyed by object
path (`ngrt.main.tickets`) and carries per-surface attachments:

```json
{ "nodes": {
  "ngrt.main.tickets": {
    "iterm":  {"tty": "…", "cwd": "…", "window_id": "…"},
    "chrome": {"group": "ngrt.main.tickets", "color": "blue", "urls": ["…"]}
}}}
```

geno-tt writes each node's `iterm` key, geno-surf its `chrome` key. geno-vault
owns none of the surfaces — it **conducts** them and **versions** the result.

## Commands

```
vault status         unified cross-surface view + vault HEAD
vault sync           pull tt + surf into the registry, then git-commit a snapshot
vault apply          push the registry back out to both surfaces
vault watch [--apply]  auto-commit on registry change (geno-pear's poll loop)
vault log            registry git history
```

## Versioning

The live registry is `~/.geno/workspace.json`; `vault` snapshots it into a git
repo at `~/.geno/vault/` on every sync, so the whole cross-surface workspace has
history — diff and revert any change.

## Watch (reused from geno-pear)

`vault watch` uses [geno-pear](https://github.com/42euge/geno-pear)'s mtime-poll
mechanism (`stat` the file each second, act on change) — the same watch pattern
that powers pear's companion — to auto-commit the registry whenever a surface
rewrites it, and optionally re-apply (`--apply`).

## Conventions
Mirrors geno-tt/geno-surf: dependency-free core, `skills/<name>/SKILL.md` named
`geno-vault-<name>`, version bumped in pyproject/genotools/`__init__`/manifests.
