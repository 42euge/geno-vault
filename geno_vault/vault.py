"""Git-versioned persistence for the shared object-notation registry.

The live registry is ~/.geno/workspace.json (written by geno-tt and geno-surf).
geno-vault snapshots it into a git repo at ~/.geno/vault/ so the whole
cross-surface workspace has history — every sync is a commit you can diff/revert.
Pure stdlib.
"""

import json
import shutil
import subprocess
from pathlib import Path

REGISTRY = Path.home() / ".geno" / "workspace.json"      # live, shared
VAULT_DIR = Path.home() / ".geno" / "vault"              # git-versioned snapshots
SNAPSHOT = VAULT_DIR / "workspace.json"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(VAULT_DIR), *args],
                          capture_output=True, text=True)


def ensure_repo() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    if not (VAULT_DIR / ".git").is_dir():
        _git("init", "-q")
        _git("config", "user.name", "geno-vault")
        _git("config", "user.email", "vault@geno")


def load_registry() -> dict:
    if REGISTRY.exists():
        try:
            d = json.loads(REGISTRY.read_text())
            d.setdefault("nodes", {})
            return d
        except (ValueError, OSError):
            pass
    return {"nodes": {}}


def snapshot(message: str) -> str | None:
    """Copy the live registry into the vault and commit. Returns short sha, or
    None if nothing changed."""
    ensure_repo()
    if not REGISTRY.exists():
        return None
    shutil.copyfile(REGISTRY, SNAPSHOT)
    _git("add", "workspace.json")
    st = _git("status", "--porcelain")
    if not st.stdout.strip():
        return None
    _git("commit", "-q", "-m", message)
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


def log(n: int = 15) -> list[str]:
    ensure_repo()
    r = _git("log", f"-{n}", "--format=%h %ad %s", "--date=format:%m-%d %H:%M")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]
