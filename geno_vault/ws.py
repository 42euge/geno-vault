"""geno-vault ws — workspace lifecycle management.

The CLI is the durability layer; the skills in skills/ws/ are thin wrappers.

Commands:
  geno-vault ws init <dot.path> [--host HOST] [--repo URL ...] [--ticket KEY]
  geno-vault ws add-repo <dot.path> --repo URL [--host HOST]
  geno-vault ws add-ticket <dot.path> --ticket KEY
  geno-vault ws open <dot.path>
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

_BOLD = "\033[1m"
_DIM  = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RESET = "\033[0m"

# Deterministic accent colour from workspace name hash (10 pleasant colours)
_PALLETE = [
    "#1a3a2a",  # green
    "#1a2a3a",  # blue
    "#2a1a3a",  # purple
    "#3a1a1a",  # red
    "#2a2a1a",  # olive
    "#1a3a3a",  # teal
    "#3a2a1a",  # brown
    "#3a3a1a",  # gold
    "#1a1a3a",  # navy
    "#2a1a1a",  # maroon
]
_FG = ["#a0e0b0", "#a0c0e0", "#c0a0e0", "#e0a0a0", "#d0d0a0",
       "#a0d0d0", "#d0c0a0", "#d0d0a0", "#a0a0d0", "#d0a0a0"]


def _accent(name: str) -> tuple[str, str]:
    i = sum(ord(c) for c in name) % len(_PALLETE)
    return _PALLETE[i], _FG[i]


def _run_ssh(host: str, cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", host, cmd],
        capture_output=True, text=True,
        **({"check": check} if check else {})
    )


def _ws_dir(dot_path: str, host: str | None) -> str:
    """Return the workspace directory path (absolute) on the target machine."""
    # dot_path like "crit.myproject.feature" → ~/code/crit/myproject/feature.2026.q2
    # or if already has born suffix → use as-is
    parts = dot_path.split(".")
    # determine born quarter from current date
    import datetime
    q = f"{datetime.date.today().year}.q{(datetime.date.today().month - 1) // 3 + 1}"
    if len(parts) >= 3:
        track, domain = parts[0], parts[1]
        workspace = ".".join(parts[2:])
        # if workspace already ends with a year.qN pattern, don't add again
        if not re.search(r"\.\d{4}\.q\d$", workspace):
            workspace = f"{workspace}.{q}"
        return f"$HOME/code/{track}/{domain}/{workspace}"
    # fallback
    return f"$HOME/code/{dot_path.replace('.', '/')}.{q}"


def _ws_name(dot_path: str) -> str:
    """Derive workspace file basename from dot_path."""
    parts = dot_path.split(".")
    if len(parts) >= 3:
        import datetime
        q = f"{datetime.date.today().year}.q{(datetime.date.today().month - 1) // 3 + 1}"
        workspace = ".".join(parts[2:])
        if not re.search(r"\.\d{4}\.q\d$", workspace):
            workspace = f"{workspace}.{q}"
        return workspace
    return dot_path


def _ticket_provider():
    """Return the configured ticket provider callable or None.

    Provider is resolved from ~/.geno/config.yaml → tickets.provider:
      github   — use `gh issue view` (default, no extra deps)
      custom   — import tickets.adapter from the path in tickets.adapter_module

    Returns a callable: (key: str) -> dict[key, summary, status, url]
    """
    try:
        import yaml as _yaml
        from pathlib import Path as _Path
        cfg_path = _Path.home() / ".geno" / "config.yaml"
        cfg = _yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
        tkt_cfg = cfg.get("tickets", {})
        provider = tkt_cfg.get("provider", "github")
        if provider == "custom":
            mod_path = tkt_cfg.get("adapter_module", "")
            if mod_path:
                import importlib.util as _ilu
                spec = _ilu.spec_from_file_location("_ticket_adapter", mod_path)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore
                return mod.fetch_ticket
        # default: github
    except Exception:
        pass
    return _github_ticket_provider


def _github_ticket_provider(key: str) -> dict:
    """Fetch a GitHub issue using the `gh` CLI.

    key format: <owner>/<repo>#<number>  or just a bare issue number if
    GITHUB_REPOSITORY is set in the environment.
    Returns: {key, summary, status, url}
    """
    import os, subprocess as _sp
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    number = key.lstrip("#")
    if "/" in key:
        parts = key.split("#")
        repo, number = parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""
    if not repo or not number:
        return {"key": key, "summary": "", "status": "", "url": ""}
    try:
        r = _sp.run(
            ["gh", "issue", "view", number, "--repo", repo,
             "--json", "title,state,url"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            import json as _j
            d = _j.loads(r.stdout)
            return {"key": key, "summary": d.get("title", ""),
                    "status": d.get("state", ""), "url": d.get("url", "")}
    except Exception:
        pass
    return {"key": key, "summary": "", "status": "", "url": ""}


def _fetch_ticket(key: str) -> dict:
    """Fetch a ticket via the configured provider. Returns {key, summary, status, url}."""
    provider = _ticket_provider()
    if provider is None:
        return {"key": key, "summary": "", "status": "", "url": ""}
    try:
        return provider(key)
    except Exception:
        return {"key": key, "summary": "", "status": "", "url": ""}


def _write_ticket_yaml(ws_dir: str, host: str | None, ticket: dict) -> None:
    key_lower = ticket["key"].lower()
    content = (
        f"ticket:\n"
        f"  key: {ticket['key']}\n"
        f"  url: {ticket['url']}\n"
        f"  summary: {ticket['summary']}\n"
        f"  status: {ticket['status']}\n"
    )
    if host:
        _run_ssh(host, f"cat > {ws_dir}/{key_lower}.yaml << 'YAML_EOF'\n{content}\nYAML_EOF", check=False)
    else:
        Path(ws_dir).expanduser().joinpath(f"{key_lower}.yaml").write_text(content)


def _write_code_workspace(ws_dir: str, ws_name: str, dot_path: str,
                          repos: list[str], host: str | None) -> str:
    """Write a .code-workspace file. repos is a list of directory basenames already cloned."""
    accent_bg, accent_fg = _accent(dot_path)
    dark_bg = accent_bg  # already dark enough
    folders = [{"name": r, "path": r} for r in repos]
    ws = {
        "folders": folders,
        "settings": {
            "window.title": f"{dot_path} — ${{rootName}}",
            "workbench.colorCustomizations": {
                "titleBar.activeBackground": accent_bg,
                "titleBar.activeForeground": accent_fg,
                "activityBar.background": dark_bg,
                "statusBar.background": accent_bg,
                "statusBar.foreground": accent_fg,
            },
            "files.exclude": {"**/build": True, "**/.loops": False, "**/target": True},
            "editor.quickSuggestions": {"other": False, "comments": False, "strings": False},
            "editor.suggestOnTriggerCharacters": False,
            "editor.wordBasedSuggestions": "off",
            "editor.parameterHints.enabled": False,
            "editor.hover.enabled": False,
            "github.copilot.enable": {"*": False},
        },
    }
    content = json.dumps(ws, indent=2)
    ws_file = f"{ws_name}.code-workspace"
    ws_path = f"{ws_dir}/{ws_file}"
    if host:
        escaped = content.replace("'", "'\\''")
        _run_ssh(host, f"printf '%s' '{escaped}' > {ws_path}", check=False)
    else:
        full = Path(ws_dir).expanduser() / ws_file
        full.write_text(content)
    return ws_path


def _register_vscode(dot_path: str, ws_path: str, host: str | None) -> None:
    """Write the vscode key into ~/.geno/workspace.json."""
    import json as _json
    reg_path = Path.home() / ".geno" / "workspace.json"
    reg: dict = {}
    if reg_path.exists():
        try:
            reg = _json.loads(reg_path.read_text())
        except Exception:
            pass
    reg.setdefault("nodes", {}).setdefault(dot_path, {})["vscode"] = {
        "workspace": ws_path,
        "host": host or "",
    }
    reg_path.write_text(_json.dumps(reg, indent=2))


def _current_repos(ws_dir: str, host: str | None) -> list[str]:
    """List git repos already cloned in the workspace dir."""
    if host:
        r = _run_ssh(host,
            f"find {ws_dir} -maxdepth 1 -mindepth 1 -type d -exec test -d {{}}/.git \\; -print",
            check=False)
        return [Path(p).name for p in r.stdout.splitlines() if p.strip()]
    root = Path(ws_dir).expanduser()
    if not root.exists():
        return []
    return [d.name for d in root.iterdir() if d.is_dir() and (d / ".git").exists()]


# ── public commands ──────────────────────────────────────────────────────────

def cmd_init(args) -> int:
    dot_path = args.dot_path
    host = getattr(args, "host", None) or ""
    host = host.strip() or None
    repos_raw: list[str] = getattr(args, "repo", []) or []
    ticket_key: str = getattr(args, "ticket", None) or ""

    ws_dir = _ws_dir(dot_path, host)
    ws_name = _ws_name(dot_path)

    print(f"{_BOLD}initialising workspace{_RESET} {dot_path}")
    print(f"  dir : {ws_dir}" + (f" on {host}" if host else " (local)"))

    # 1 — mkdir
    if host:
        r = _run_ssh(host, f"mkdir -p {ws_dir} && echo ok", check=False)
        if "ok" not in r.stdout:
            print(f"  {_YELLOW}mkdir failed: {r.stderr.strip()}{_RESET}", file=sys.stderr)
            return 1
    else:
        Path(ws_dir).expanduser().mkdir(parents=True, exist_ok=True)
    print(f"  {_GREEN}✓{_RESET} directory created")

    # 2 — clone repos
    cloned: list[str] = []
    for repo_url in repos_raw:
        if not repo_url.startswith("http") and not repo_url.startswith("git@"):
            repo_url = _expand_repo_url(repo_url, host)
        name = repo_url.rstrip("/").rstrip(".git").split("/")[-1]
        print(f"  cloning {name}…", end=" ", flush=True)
        if host:
            r = _run_ssh(host, f"git clone --quiet '{repo_url}' {ws_dir}/{name} 2>&1 | tail -1", check=False)
            ok = r.returncode == 0
        else:
            r = subprocess.run(["git", "clone", "--quiet", repo_url,
                                str(Path(ws_dir).expanduser() / name)],
                               capture_output=True, text=True)
            ok = r.returncode == 0
        print(f"{_GREEN}✓{_RESET}" if ok else f"{_YELLOW}✗ {(r.stderr or r.stdout).strip()[:60]}{_RESET}")
        if ok:
            cloned.append(name)

    # 3 — .code-workspace
    if cloned:
        ws_path = _write_code_workspace(ws_dir, ws_name, dot_path, cloned, host)
        print(f"  {_GREEN}✓{_RESET} workspace file: {ws_path}")

        # 4 — register vscode key in ~/.geno/workspace.json
        _register_vscode(dot_path, ws_path, host)
        print(f"  {_GREEN}✓{_RESET} registered in registry")

    # 5 — ticket context
    if ticket_key:
        ticket = _fetch_ticket(ticket_key.upper())
        _write_ticket_yaml(ws_dir, host, ticket)
        print(f"  {_GREEN}✓{_RESET} ticket context: {ticket['key']} — {ticket['summary']}")

    # 6 — open VS Code
    open_cmd = (f"code --remote ssh-remote+{host} {ws_path}"
                if host else f"code {ws_path}") if cloned else ""
    print(f"\n{_BOLD}workspace ready{_RESET}")
    if open_cmd:
        print(f"  open : {_DIM}{open_cmd}{_RESET}")
    return 0


def cmd_add_repo(args) -> int:
    dot_path = args.dot_path
    host = (getattr(args, "host", None) or "").strip() or None
    repo_url: str = args.repo

    ws_dir = _ws_dir(dot_path, host)
    ws_name = _ws_name(dot_path)

    if not repo_url.startswith("http") and not repo_url.startswith("git@"):
        repo_url = _expand_repo_url(repo_url, host)

    name = repo_url.rstrip("/").rstrip(".git").split("/")[-1]
    print(f"cloning {name} into {dot_path}…", end=" ", flush=True)
    if host:
        r = _run_ssh(host, f"git clone --quiet '{repo_url}' {ws_dir}/{name} 2>&1 | tail -1", check=False)
        ok = r.returncode == 0
    else:
        r = subprocess.run(["git", "clone", "--quiet", repo_url,
                            str(Path(ws_dir).expanduser() / name)],
                           capture_output=True, text=True)
        ok = r.returncode == 0

    print(f"{_GREEN}✓{_RESET}" if ok else f"{_YELLOW}✗ {(r.stderr or r.stdout).strip()[:80]}{_RESET}")
    if not ok:
        return 1

    # Regenerate .code-workspace with updated repo list
    repos = _current_repos(ws_dir, host)
    ws_path = _write_code_workspace(ws_dir, ws_name, dot_path, repos, host)
    _register_vscode(dot_path, ws_path, host)
    print(f"workspace updated: {len(repos)} repo(s)")
    return 0


def cmd_add_ticket(args) -> int:
    dot_path = args.dot_path
    host = (getattr(args, "host", None) or "").strip() or None
    ticket_key: str = args.ticket.upper()

    ws_dir = _ws_dir(dot_path, host)
    ticket = _fetch_ticket(ticket_key)
    _write_ticket_yaml(ws_dir, host, ticket)
    print(f"wrote {ticket_key.lower()}.yaml — {ticket['summary']}")
    return 0


def cmd_open(args) -> int:
    dot_path = args.dot_path
    import json as _json
    reg_path = Path.home() / ".geno" / "workspace.json"
    if not reg_path.exists():
        print("registry not found", file=sys.stderr); return 1
    node = _json.loads(reg_path.read_text()).get("nodes", {}).get(dot_path, {})
    vs = node.get("vscode")
    if not vs or not vs.get("workspace"):
        print(f"no VS Code workspace registered for {dot_path}", file=sys.stderr); return 1
    ws_path, h = vs["workspace"], vs.get("host", "")
    argv = ["code", "--remote", f"ssh-remote+{h}", ws_path] if h else ["code", ws_path]
    subprocess.Popen(argv)
    print(f"opening {ws_path}" + (f" on {h}" if h else ""))
    return 0


def _expand_repo_url(short: str, host: str | None) -> str:
    """Expand a short repo path to a full authenticated clone URL.

    Resolution order:
      1. ~/.geno/config.yaml → git.hosts[<name>].base_url + token
      2. Environment: GIT_TOKEN or GITLAB_TOKEN
      3. SSH fallback: git@<base_host>:<short>.git

    config.yaml example:
      git:
        default_host: myforge
        hosts:
          myforge:
            base_url: https://git.example.com
            token_env: GIT_TOKEN   # env var holding the PAT
            ssh_host: git.example.com
    """
    try:
        import os, yaml as _yaml
        from pathlib import Path as _Path
        cfg_path = _Path.home() / ".geno" / "config.yaml"
        cfg = _yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
        git_cfg = cfg.get("git", {})
        default_host = git_cfg.get("default_host", "")
        hosts = git_cfg.get("hosts", {})
        hcfg = hosts.get(default_host, {})
        base_url = hcfg.get("base_url", "").rstrip("/")
        token_env = hcfg.get("token_env", "GIT_TOKEN")
        token = os.environ.get(token_env, "")
        if base_url and token:
            # strip leading protocol for oauth2 injection
            bare = base_url.split("://", 1)[-1]
            return f"https://oauth2:{token}@{bare}/{short}.git"
        if base_url:
            return f"{base_url}/{short}.git"
        # SSH fallback
        ssh_host = hcfg.get("ssh_host", "")
        if ssh_host:
            return f"git@{ssh_host}:{short}.git"
    except Exception:
        pass
    # last resort: treat as bare SSH path
    return f"git@localhost:{short}.git"
