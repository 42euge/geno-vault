---
name: geno-vault
description: >-
  Persistence + sync conductor for the geno object-notation registry (the
  `vault` CLI). Use to sync geno-tt (iTerm) and geno-surf (Chromium) through one
  git-versioned registry, or to watch/apply registry changes.
allowed-tools: "Bash(vault *)"
metadata:
  author: 42euge
  version: "0.2.0"
---

# geno-vault — registry sync conductor

`vault` git-versions ~/.geno/workspace.json and conducts pull/push across
surfaces. `sync` pulls tt+surf in and commits; `apply` pushes out; `watch`
auto-commits on change (geno-pear poll); `status`/`log` inspect.
