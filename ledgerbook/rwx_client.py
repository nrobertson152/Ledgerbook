# SPDX-License-Identifier: GPL-3.0-or-later
"""RevisionWorx client for other programs (Caldera, Ledgerbook, OpenSchematix Viewer, TraceMarx, ...).

Copy this single file into your program (it is the reference client for docs/INTEGRATION.md in the
RevisionWorx repository; keep the RWX_CLIENT_VERSION line so copies can be compared). Standard library only,
Python 3.9+, no GUI toolkit. It runs the ``revisionworx`` command (``revisionworx link ...``) and parses its
one-object JSON answer, so it works with a pip install or the standalone build of RevisionWorx, and your
program keeps working, with the integration hidden, when RevisionWorx is not installed.

    from rwx_client import RevisionWorx, RwxError
    rwx = RevisionWorx()                      # finds the revisionworx command
    if rwx.available():
        info = rwx.status("/path/to/file.pdf")          # is this file controlled? what revision?
        rwx.publish("report.pdf", project="J-1", number="CALC-7", title="Pump sizing", message="Initial")

Locating RevisionWorx, first match wins: the ``executable`` argument, the REVISIONWORX_CLI environment variable,
``revisionworx`` on PATH, the standalone build in the usual install folders, then ``python -m revisionworx`` if
the package is importable.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

RWX_CLIENT_VERSION = 1
API_VERSION = 1
_TIMEOUT = 120


class RwxError(Exception):
    """RevisionWorx refused or could not do something. ``kind``: not-found, checked-out, busy, no-workspace,
    bad-input, refused, unavailable, error. The message is written for the person using your program."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.kind = kind


def _standalone_candidates() -> List[Path]:
    names = ["revisionworx.exe"] if os.name == "nt" else ["revisionworx"]
    roots: List[Path] = []
    if os.name == "nt":
        for var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            if os.environ.get(var):
                roots.append(Path(os.environ[var]))
        roots.append(Path.home() / "Downloads")
    else:
        roots += [Path.home() / "Applications", Path.home() / ".local" / "opt", Path("/opt"), Path.home()]
    out = []
    for root in roots:
        try:
            for folder in sorted(root.glob("RevisionWorx*"), reverse=True):
                for name in names:
                    if (folder / name).is_file():
                        out.append(folder / name)
        except OSError:
            continue
    return out


def find_command(executable: Optional[str] = None) -> Optional[List[str]]:
    """The command prefix that runs RevisionWorx, or None if it cannot be found."""
    for candidate in (executable, os.environ.get("REVISIONWORX_CLI")):
        if candidate:
            return [candidate]
    found = shutil.which("revisionworx")
    if found:
        return [found]
    for exe in _standalone_candidates():
        return [str(exe)]
    try:
        import importlib.util
        if importlib.util.find_spec("revisionworx") is not None and not getattr(sys, "frozen", False):
            return [sys.executable, "-m", "revisionworx"]
    except (ImportError, ValueError):
        pass
    return None


class RevisionWorx:
    """One RevisionWorx installation. ``workspace``: a workspace folder to use for every call (default: the
    file's own workspace, REVISIONWORX_WORKSPACE, or the one most recently opened in RevisionWorx)."""

    def __init__(self, executable: Optional[str] = None, workspace: Optional[str] = None, timeout: int = _TIMEOUT):
        self.command = find_command(executable)
        self.workspace = workspace
        self.timeout = timeout
        self._version: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------ plumbing
    def available(self) -> bool:
        """True when RevisionWorx is installed and speaks a compatible integration API."""
        if self.command is None:
            return False
        try:
            v = self.version()
        except RwxError:
            return False
        return v.get("api") == API_VERSION

    def _run(self, *args: str) -> Dict[str, Any]:
        if self.command is None:
            raise RwxError("RevisionWorx is not installed (or not found). Install it, or set the "
                           "REVISIONWORX_CLI environment variable to its 'revisionworx' program.", "unavailable")
        cmd = list(self.command)
        if self.workspace:
            cmd += ["-w", str(self.workspace)]
        cmd += ["link", *[str(a) for a in args]]
        kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000           # CREATE_NO_WINDOW: no console flashes up
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=self.timeout, stdin=subprocess.DEVNULL, **kwargs)
        except FileNotFoundError:
            raise RwxError(f"could not run {cmd[0]}", "unavailable") from None
        except subprocess.TimeoutExpired:
            raise RwxError("RevisionWorx did not answer in time (is the workspace busy or offline?)", "busy") from None
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        try:
            data = json.loads(lines[-1]) if lines else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise RwxError("RevisionWorx gave an unexpected answer" + (f": {detail[-1]}" if detail else ""),
                           "error")
        if not data.get("ok"):
            raise RwxError(data.get("error") or "RevisionWorx refused the request", data.get("kind") or "error")
        return data

    # ------------------------------------------------------------------ calls
    def version(self) -> Dict[str, Any]:
        if self._version is None:
            self._version = self._run("version")
        return self._version

    def workspaces(self) -> List[Dict[str, Any]]:
        return self._run("workspaces")["workspaces"]

    def status(self, file: str) -> Dict[str, Any]:
        """{"controlled": bool, "document": {...} or None, "file": {"state", "matches_latest"}, "workspace": ...}"""
        return self._run("status", os.path.abspath(file))

    def projects(self) -> List[Dict[str, Any]]:
        return self._run("projects")["projects"]

    def documents(self, project: Optional[str] = None, text: str = "") -> List[Dict[str, Any]]:
        args = ["documents"] + (["--project", project] if project else []) + (["--text", text] if text else [])
        return self._run(*args)["documents"]

    def document(self, ref: str, project: Optional[str] = None) -> Dict[str, Any]:
        return self._run("document", ref, *(["--project", project] if project else []))["document"]

    def fetch(self, ref: str, to_dir: str, revision: Optional[str] = None, released: bool = False,
              project: Optional[str] = None) -> Dict[str, Any]:
        """Copy one revision to ``to_dir`` for reading. Returns {"path", "revision": {...}, ...}."""
        args = ["fetch", ref, "--to", os.path.abspath(to_dir)]
        if revision:
            args += ["--revision", revision]
        if released:
            args.append("--released")
        if project:
            args += ["--project", project]
        return self._run(*args)

    def publish(self, file: str, project: Optional[str] = None, document: Optional[str] = None, number: str = "",
                title: str = "", folder: str = "", message: str = "") -> Dict[str, Any]:
        """New document in ``project``, or a new revision of ``document`` (or of the document numbered ``number``).
        Returns {"result": "created" | "revised" | "unchanged", "document": {...}, ...}."""
        args = ["publish", os.path.abspath(file)]
        for flag, value in (("--project", project), ("--document", document), ("--number", number),
                            ("--title", title), ("--folder", folder), ("--message", message)):
            if value:
                args += [flag, value]
        return self._run(*args)

    def open(self, document: Optional[str] = None, file: Optional[str] = None) -> Dict[str, Any]:
        """Show a document in the RevisionWorx window."""
        args = ["open"] + (["--document", document] if document else []) + (["--file", os.path.abspath(file)]
                                                                             if file else [])
        return self._run(*args)


def describe(status: Dict[str, Any]) -> str:
    """One line for a status bar: 'DWG-1 rev B · Released · checked out by you', or '' for an uncontrolled file."""
    if not status.get("controlled"):
        return ""
    doc = status["document"]
    latest = doc.get("latest") or {}
    parts = [f"{doc.get('number') or doc.get('title') or 'Document'} rev {latest.get('label', '?')}",
             latest.get("state_name", "")]
    co = doc.get("checkout")
    if co:
        parts.append("checked out by you" if co.get("mine") else f"checked out by {co.get('user', '?')}")
    state = (status.get("file") or {}).get("state")
    if state in ("modified", "modified-externally"):
        parts.append("this file differs from the latest revision")
    elif state == "missing":
        parts.append("file missing")
    return " · ".join(p for p in parts if p)
