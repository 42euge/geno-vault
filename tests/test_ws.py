"""Tests for geno_vault.ws — workspace lifecycle management."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from geno_vault import ws as _ws


# ── _ws_dir ──────────────────────────────────────────────────────────────────

def test_ws_dir_three_parts():
    d = _ws._ws_dir("crit.myproject.feature", host=None)
    assert d.startswith("$HOME/code/crit/myproject/feature.")
    assert ".q" in d   # has quarter suffix


def test_ws_dir_preserves_born():
    d = _ws._ws_dir("crit.myproject.feature.2026.q2", host=None)
    assert d.endswith("feature.2026.q2")
    # no double quarter appended
    assert d.count("2026") == 1


def test_ws_name_three_parts():
    name = _ws._ws_name("crit.myproject.feature")
    assert name.startswith("feature.")
    assert ".q" in name


# ── _accent ───────────────────────────────────────────────────────────────────

def test_accent_deterministic():
    bg1, fg1 = _ws._accent("crit.myproject.feature")
    bg2, fg2 = _ws._accent("crit.myproject.feature")
    assert bg1 == bg2 and fg1 == fg2


def test_accent_different_paths():
    bg1, _ = _ws._accent("crit.myproject.feature")
    bg2, _ = _ws._accent("side.otherproject.work")
    assert bg1.startswith("#") and len(bg1) == 7
    assert bg2.startswith("#") and len(bg2) == 7


# ── _write_code_workspace ────────────────────────────────────────────────────

def test_write_code_workspace_local(tmp_path):
    ws_path = _ws._write_code_workspace(
        str(tmp_path), "feature.2026.q2", "crit.myproject.feature",
        ["repo-a", "deploy"], host=None)
    f = tmp_path / "feature.2026.q2.code-workspace"
    assert f.exists()
    data = json.loads(f.read_text())
    paths = [folder["path"] for folder in data["folders"]]
    assert "repo-a" in paths
    assert "deploy" in paths
    assert "crit.myproject.feature" in data["settings"]["window.title"]
    assert "workbench.colorCustomizations" in data["settings"]
    assert ws_path == str(f)


def test_write_code_workspace_no_copilot(tmp_path):
    _ws._write_code_workspace(str(tmp_path), "ws", "a.b.c", ["repo"], host=None)
    f = tmp_path / "ws.code-workspace"
    data = json.loads(f.read_text())
    copilot = data["settings"].get("github.copilot.enable", {})
    assert copilot.get("*") is False


# ── _register_vscode ─────────────────────────────────────────────────────────

def test_register_vscode_creates_entry(tmp_path):
    reg_path = tmp_path / ".geno" / "workspace.json"
    reg_path.parent.mkdir(parents=True)
    reg_path.write_text(json.dumps({"nodes": {}}))

    import geno_vault.ws as ws_module
    orig_home = ws_module.Path.home
    ws_module.Path.home = lambda: tmp_path
    try:
        _ws._register_vscode("crit.myproject.feature", "/path/to/ws", "devbox")
        data = json.loads(reg_path.read_text())
        assert "crit.myproject.feature" in data["nodes"]
        vs = data["nodes"]["crit.myproject.feature"]["vscode"]
        assert vs["workspace"] == "/path/to/ws"
        assert vs["host"] == "devbox"
    finally:
        ws_module.Path.home = orig_home


def test_register_vscode_preserves_existing(tmp_path):
    existing = {
        "nodes": {
            "crit.myproject.feature": {
                "iterm": {"tty": "/dev/ttys001"},
                "chrome": None
            }
        }
    }
    reg_path = tmp_path / ".geno" / "workspace.json"
    reg_path.parent.mkdir(parents=True)
    reg_path.write_text(json.dumps(existing))

    import geno_vault.ws as ws_module
    orig_home = ws_module.Path.home
    ws_module.Path.home = lambda: tmp_path
    try:
        _ws._register_vscode("crit.myproject.feature", "/ws/file", "devbox")
        data = json.loads(reg_path.read_text())
        node = data["nodes"]["crit.myproject.feature"]
        assert node["vscode"]["workspace"] == "/ws/file"
        assert node["iterm"]["tty"] == "/dev/ttys001"
    finally:
        ws_module.Path.home = orig_home


# ── _current_repos ────────────────────────────────────────────────────────────

def test_current_repos_local(tmp_path):
    (tmp_path / "repo-a" / ".git").mkdir(parents=True)
    (tmp_path / "repo-b" / ".git").mkdir(parents=True)
    (tmp_path / "notarepo").mkdir()
    repos = _ws._current_repos(str(tmp_path), host=None)
    assert set(repos) == {"repo-a", "repo-b"}


def test_current_repos_empty_dir(tmp_path):
    repos = _ws._current_repos(str(tmp_path), host=None)
    assert repos == []


# ── _ws_dir path expansion ────────────────────────────────────────────────────

def test_ws_dir_remote_uses_home_var():
    d = _ws._ws_dir("crit.myproject.feature", host="devbox")
    assert d.startswith("$HOME/")
