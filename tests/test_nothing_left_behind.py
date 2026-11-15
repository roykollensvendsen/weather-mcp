"""A run of the tests or the checks leaves nothing in the temporary folder.

Folders left by test, mutation and ratchet runs once filled the machine's temporary
folder. Each test here points TMPDIR at a folder of its own, runs the thing, and
looks at what is left.
"""

import os
import pathlib
import subprocess
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _left(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def test_a_test_run_leaves_nothing_in_the_temporary_folder(tmp_path):
    """The folders pytest makes for tmp_path are removed when the run ends, not kept."""
    spare = tmp_path / "tmp"
    spare.mkdir()
    env = {**os.environ, "TMPDIR": str(spare)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_disk_cache.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout[-2000:]
    leftover = [p for p in _left(spare) if not p.startswith("pytest-of-") or "/" in p]
    assert leftover == [], f"left in the temporary folder: {leftover}"


# Measures main in a copy, and is stopped the way CI cancels a job, while installing it.
STOPPED_WHILE_MEASURING = textwrap.dedent(
    """
    import importlib.util, os, pathlib, signal, subprocess, sys
    spec = importlib.util.spec_from_file_location("ratchet", sys.argv[1])
    ratchet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ratchet)
    removed = pathlib.Path(sys.argv[2])

    def run(*command, cwd=None, env=None):
        if command[:3] == ("git", "worktree", "add"):
            pathlib.Path(command[-2]).mkdir()
            (pathlib.Path(command[-2]) / "a-file").write_text("the copy of main")
        elif command[:3] == ("git", "worktree", "remove"):
            removed.write_text("removed")
        elif command[:2] == ("uv", "sync"):
            os.kill(os.getpid(), signal.SIGTERM)
        return subprocess.CompletedProcess(command, 0, "", "")

    ratchet._run = run
    ratchet.stop_cleanly()
    ratchet.measure_at("main")
    """
)


def test_a_ratchet_stopped_from_outside_removes_what_it_made(tmp_path):
    spare = tmp_path / "tmp"
    spare.mkdir()
    removed = tmp_path / "worktree-removed"
    env = {**os.environ, "TMPDIR": str(spare)}
    done = subprocess.run(
        [sys.executable, "-c", STOPPED_WHILE_MEASURING, str(ROOT / "scripts/ratchet.py"), str(removed)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0, "it was stopped, so it must not report success"
    assert _left(spare) == [], f"left in the temporary folder: {_left(spare)}"
    assert removed.exists(), "the git worktree entry for the copy must be removed too"
