"""vault serve — persistent iTerm2 watcher + tab possession daemon.

Holds a long-lived iTerm2 Python API connection and subscribes to
layout change events. On every change it:

  1. Scans every live tab for a dot-notation sticky title.
  2. Upserts the matching registry node's iterm key (tty / cwd / window_id).
  3. Removes the iterm key from any node that had one but whose tab is gone.
  4. Commits a vault snapshot if the registry changed.
  5. Tints the session's tab with the color of its linked Chrome group
     (teal fallback). This is the visual "possession" signal: a tab that
     changes from default to tinted is now under daemon control.

Chrome group colors follow the same map as the GUI's CHROME_COLORS dict.
Tab tinting uses iTerm2's per-session profile override
(LocalWriteOnlyProfile.set_tab_color + set_use_tab_color), which is
non-destructive — the base profile is unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time

log = logging.getLogger("vault.daemon")

# Map Chrome group color names → (r, g, b) in 0-255
_CHROME_RGB: dict[str, tuple[int, int, int]] = {
    "grey":   (95,  99, 104),
    "blue":   (26, 115, 232),
    "red":    (217, 48,  37),
    "yellow": (249, 171,  0),
    "green":  (30, 142,  62),
    "pink":   (208, 24, 132),
    "purple": (161,  66, 244),
    "cyan":   (18, 181, 203),
    "orange": (250, 144,  62),
}

# Teal fallback for nodes with no Chrome group
_FALLBACK_RGB = (0, 175, 170)

APP_NAME = "geno-vault-daemon"


def _auth() -> None:
    try:
        out = subprocess.run(
            ["osascript", "-e",
             f'tell application "iTerm2" to request cookie and key for app named "{APP_NAME}"'],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise SystemExit(f"Could not get iTerm2 API cookie: {e}") from e
    parts = out.stdout.split()
    if out.returncode != 0 or len(parts) < 2:
        raise SystemExit(
            "Could not get an iTerm2 API cookie. Is iTerm2 running and "
            "Settings ▸ General ▸ Magic ▸ Enable Python API on?")
    os.environ["ITERM2_COOKIE"], os.environ["ITERM2_KEY"] = parts[0], parts[1]


async def _tab_title(tab) -> str:
    """Sticky tab title (the dot-notation node name)."""
    return (await tab.async_get_variable("title")) or ""


def _is_managed(title: str) -> bool:
    return "." in title.strip()


def _clean(title: str) -> str:
    return title.lstrip("✳⠂⠐⠠ ").strip()


async def _tint(session, rgb: tuple[int, int, int] | None) -> None:
    """Apply (or clear) the tab color for a session."""
    try:
        import iterm2
        p = iterm2.LocalWriteOnlyProfile()
        if rgb:
            p.set_tab_color(iterm2.Color(*rgb))
            p.set_use_tab_color(True)
        else:
            p.set_use_tab_color(False)
        await session.async_set_profile_properties(p)
    except Exception as e:  # noqa: BLE001
        log.debug("tint failed: %s", e)


async def _run_daemon(iterm2, connection, vault_module) -> None:
    """Main async daemon loop — runs inside iterm2.run_forever."""
    app = await iterm2.async_get_app(connection)
    log.info("daemon connected to iTerm2")

    # Track which session_ids we've already tinted so we only re-tint on change.
    _tinted: dict[str, tuple[int, int, int] | None] = {}
    # Track sticky titles so we can re-enforce them if iTerm drifts the title.
    _sticky: dict[str, str] = {}  # tab_id → dot-notation title
    # Separate set for "seen" sessions — warn about unnamed tabs ONCE only.
    _seen: set[str] = set()

    async def _enforce_title(tab, title: str) -> None:
        """Re-apply sticky title if iTerm2 let it drift (e.g. Claude re-titled it)."""
        current = _clean(await _tab_title(tab))
        if current != title:
            try:
                await tab.async_set_title(title)
                log.debug("re-enforced title %s (was %r)", title, current)
            except Exception as e:  # noqa: BLE001
                log.debug("title re-enforce failed for %s: %s", title, e)

    async def scan_and_sync() -> None:
        reg = vault_module.load_registry()
        nodes = reg.setdefault("nodes", {})

        # Build a map of dot-notation title → tab info from live tabs
        live: dict[str, dict] = {}
        for w in app.windows:
            for t in w.tabs:
                raw_title = await _tab_title(t)
                title = _clean(raw_title)
                if not _is_managed(title):
                    # Warn ONCE per session about unnamed tabs
                    for s in t.sessions:
                        sid = s.session_id
                        if sid not in _seen:
                            _seen.add(sid)
                            job = (await s.async_get_variable("jobName")) or ""
                            tty = (await s.async_get_variable("tty")) or ""
                            log.warning("unnamed tab — tty=%s job=%s title=%r  (run: tt name -i)",
                                        tty, job, raw_title)
                    continue
                s0 = t.sessions[0]
                live[title] = {
                    "tty": (await s0.async_get_variable("tty")) or "",
                    "cwd": (await s0.async_get_variable("path")) or "",
                    "window_id": w.window_id,
                    "_session": s0,
                    "_tab": t,
                }
                # Re-enforce sticky title if it drifted
                if _sticky.get(t.tab_id) == title:
                    await _enforce_title(t, title)
                else:
                    _sticky[t.tab_id] = title

        changed = False

        # Add / update iterm keys for currently-live managed tabs
        for title, info in live.items():
            node = nodes.setdefault(title, {})
            new_iterm = {
                "tty": info["tty"], "cwd": info["cwd"],
                "window_id": info["window_id"],
            }
            if node.get("iterm") != new_iterm:
                node["iterm"] = new_iterm
                changed = True

            # Determine tint: Chrome group color if linked, else fallback
            chrome = node.get("chrome", {})
            rgb = _CHROME_RGB.get(chrome.get("color", ""), _FALLBACK_RGB) if chrome else _FALLBACK_RGB
            session = info["_session"]
            sid = session.session_id
            if _tinted.get(sid) != rgb:
                await _tint(session, rgb)
                _tinted[sid] = rgb
                log.debug("tinted %s → %s", title, rgb)
            # Mark all panes in this managed tab as seen
            if "_tab" in info:
                for s in info["_tab"].sessions:
                    _seen.add(s.session_id)

        # Remove iterm key from nodes whose tab has been closed
        for title, node in list(nodes.items()):
            if "iterm" in node and title not in live:
                del node["iterm"]
                changed = True
                log.info("cleared stale iterm key: %s", title)
                _tinted.pop(title, None)

        # Prune nodes that have no surfaces at all — don't let the registry
        # accumulate ghost entries from sessions that closed long ago.
        for title in [k for k, v in nodes.items()
                      if not v.get("iterm") and not v.get("chrome")]:
            del nodes[title]
            changed = True
            log.info("pruned empty node: %s", title)

        if changed:
            reg["nodes"] = nodes
            import json as _json
            vault_module.REGISTRY.write_text(_json.dumps(reg, indent=2))
            sha = vault_module.snapshot(f"daemon: layout change {time.strftime('%H:%M:%S')}")
            log.info("committed snapshot %s (%d nodes, %d live tabs)",
                     sha or "(no-op)", len(nodes), len(live))

    # Initial scan on connect
    await scan_and_sync()

    # new_session fires on tab/pane open; terminate_session fires on close.
    # Title renames (tt iterm name) are caught by the 3s poll fallback below.
    queue: asyncio.Queue = asyncio.Queue()

    async def _enqueue(_conn, _msg):
        await queue.put(1)

    tokens = []
    tokens.append(await iterm2.notifications.async_subscribe_to_new_session_notification(
        connection, _enqueue))
    tokens.append(await iterm2.notifications.async_subscribe_to_terminate_session_notification(
        connection, _enqueue))

    log.info("watching for session open/close events (+ 3s poll for renames)…")

    async def _poll():
        """3-second fallback poll — catches title renames that notifications miss."""
        while True:
            await asyncio.sleep(3)
            await queue.put(1)

    asyncio.ensure_future(_poll())

    try:
        while True:
            await queue.get()
            # Drain burst
            await asyncio.sleep(0.1)
            while not queue.empty():
                queue.get_nowait()
            await scan_and_sync()
    finally:
        for tok in tokens:
            try:
                await iterm2.notifications.async_unsubscribe(connection, tok)
            except Exception:  # noqa: BLE001
                pass


def run(verbose: bool = False) -> None:
    """Entry point: authenticate then enter the iTerm2 event loop forever."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        import iterm2
    except ImportError:
        raise SystemExit(
            "geno-vault serve needs the iterm2 package.\n"
            "  pipx inject geno-vault iterm2\n"
            "and enable iTerm2 ▸ Settings ▸ General ▸ Magic ▸ Enable Python API."
        )

    from . import vault as vault_module

    _auth()

    def _quiet(loop, ctx):
        exc = ctx.get("exception")
        if exc and type(exc).__name__ in (
                "ConnectionClosedError", "ConnectionClosedOK", "CancelledError"):
            return
        loop.default_exception_handler(ctx)

    async def _main(connection):
        asyncio.get_running_loop().set_exception_handler(_quiet)
        await _run_daemon(iterm2, connection, vault_module)

    log.info("vault daemon starting (Ctrl-C to stop)")
    try:
        iterm2.run_forever(_main)
    except KeyboardInterrupt:
        log.info("daemon stopped.")
