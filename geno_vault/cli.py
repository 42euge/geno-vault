#!/usr/bin/env python3
"""vault — persistence + sync conductor for the geno object-notation registry.

The registry (~/.geno/workspace.json) is the source of truth shared by geno-tt
(iTerm) and geno-surf (Chromium). geno-vault:
  * sync   — pull every surface's state into the registry, then git-commit it
  * apply  — push the registry back out to the surfaces
  * status — the unified cross-surface view + vault HEAD
  * watch  — geno-pear's mtime-poll loop: auto-commit the registry on change
  * log    — the registry's git history
"""

import shutil
import subprocess
import sys
import time

from . import vault

_BOLD, _DIM, _RESET = "\033[1m", "\033[2m", "\033[0m"


def _run(cmd: list[str]) -> str:
    if not shutil.which(cmd[0]):
        return f"{_DIM}({cmd[0]} not installed — skipped){_RESET}"
    r = subprocess.run(cmd, capture_output=True, text=True)
    return (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else "ok"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    cmd = argv[0] if argv else "status"

    if cmd in ("-h", "--help"):
        print("geno-vault — sync conductor for the geno object-notation registry")
        print("  geno-vault status         Unified cross-surface view + vault HEAD")
        print("  geno-vault sync           Pull tt + surf into the registry, commit snapshot")
        print("  geno-vault apply          Push the registry out to the surfaces")
        print("  geno-vault watch [--apply]  Auto-commit on registry change (geno-pear poll)")
        print("  geno-vault log            Registry git history")
        print("  geno-vault gui [--port N] [--no-open]  Local web control panel")
        print("  geno-vault serve [--verbose]  Persistent daemon: watch iTerm2 layout events,")
        print("                               keep registry in sync, tint managed tabs")
        print("  geno-vault ws <sub>       Workspace management:")
        print("    ws init <path> [--host H] [--repo URL ...] [--ticket KEY]")
        print("    ws add-repo <path> --repo URL [--host H]")
        print("    ws add-ticket <path> --ticket KEY")
        print("    ws open <path>")
        return 0

    if cmd == "status":
        reg = vault.load_registry()
        nodes = reg.get("nodes", {})
        print(f"{_BOLD}registry{_RESET} {_DIM}({vault.REGISTRY}){_RESET} — {len(nodes)} node(s)")
        for path, node in sorted(nodes.items()):
            surf = []
            if "iterm" in node:
                surf.append(f"iterm:{node['iterm'].get('cwd') or node['iterm'].get('tty','?')}")
            if "chrome" in node:
                surf.append(f"chrome:{len(node['chrome'].get('urls', []))}t/{node['chrome'].get('color','')}")
            print(f"  {_BOLD}{path}{_RESET}  {_DIM}[{' · '.join(surf) or 'no surfaces'}]{_RESET}")
        hist = vault.log(1)
        print(f"{_DIM}vault HEAD: {hist[0] if hist else '(no commits yet — run geno-vault sync)'}{_RESET}")

    elif cmd == "sync":
        print("pulling surfaces into the registry…")
        print(f"  tt   → {_run(['tt', 'iterm', 'reg', 'pull'])}")
        print(f"  surf → {_run(['surf', 'reg', 'pull'])}")
        sha = vault.snapshot("sync: " + time.strftime("%Y-%m-%d %H:%M"))
        print(f"{_BOLD}committed{_RESET} {sha}" if sha else f"{_DIM}no change to commit{_RESET}")

    elif cmd == "apply":
        print("pushing the registry out to the surfaces…")
        print(f"  surf → {_run(['surf', 'reg', 'push'])}")
        print(f"  tt   → {_run(['tt', 'iterm', 'reg', 'push'])}")

    elif cmd == "log":
        for line in vault.log(20):
            print(f"  {line}")

    elif cmd == "gui":
        from . import gui
        port = 8787
        if "--port" in argv:
            port = int(argv[argv.index("--port") + 1])
        gui.serve(port=port, open_browser="--no-open" not in argv)

    elif cmd == "watch":
        apply = "--apply" in argv
        f = vault.REGISTRY
        if not f.exists():
            raise SystemExit(f"registry {f} doesn't exist yet — run geno-vault sync first.")

        def _on_change(_path):
            sha = vault.snapshot("watch: registry changed " + time.strftime("%H:%M:%S"))
            print(f"  {time.strftime('%H:%M:%S')} changed → committed {sha or '(no-op)'}")
            if apply:
                _run(["surf", "reg", "push"]); _run(["tt", "iterm", "reg", "push"])

        # Compose the ecosystem: use geno-pear's watch library if installed,
        # else fall back to the same mechanism inline (keeps geno-vault standalone).
        try:
            from geno_pear import watch as pear_watch
            src = "geno-pear library"
        except ImportError:
            pear_watch = None
            src = "built-in poll (pip install 'geno-vault[watch]' for the shared geno-pear watcher)"
        print(f"watching {f} via {src}. Ctrl-C to stop.")
        try:
            if pear_watch:
                pear_watch(f, _on_change, interval=1.0)
            else:
                last = f.stat().st_mtime
                while True:
                    cur = f.stat().st_mtime if f.exists() else last
                    if cur != last:
                        last = cur
                        _on_change(str(f))
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\nstopped.")

    elif cmd == "serve":
        from . import daemon
        daemon.run(verbose="--verbose" in argv)

    elif cmd == "ws":
        import argparse
        from . import ws as _ws
        sub = argv[1] if len(argv) > 1 else "--help"
        p = argparse.ArgumentParser(prog="geno-vault ws", add_help=False)
        subs = p.add_subparsers(dest="ws_cmd")

        p_init = subs.add_parser("init")
        p_init.add_argument("dot_path")
        p_init.add_argument("--host", default="")
        p_init.add_argument("--repo", action="append", default=[])
        p_init.add_argument("--ticket", default="")

        p_add = subs.add_parser("add-repo")
        p_add.add_argument("dot_path")
        p_add.add_argument("--repo", required=True)
        p_add.add_argument("--host", default="")

        p_tkt = subs.add_parser("add-ticket")
        p_tkt.add_argument("dot_path")
        p_tkt.add_argument("--ticket", required=True)
        p_tkt.add_argument("--host", default="")

        p_open = subs.add_parser("open")
        p_open.add_argument("dot_path")

        args = p.parse_args(argv[1:])
        dispatch = {
            "init":       _ws.cmd_init,
            "add-repo":   _ws.cmd_add_repo,
            "add-ticket": _ws.cmd_add_ticket,
            "open":       _ws.cmd_open,
        }
        if not args.ws_cmd or args.ws_cmd not in dispatch:
            p.print_help()
            return 1
        return dispatch[args.ws_cmd](args)

    else:
        raise SystemExit(f"Unknown command '{cmd}'. Try: geno-vault --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
