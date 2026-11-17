"""A run of the tests or the checks leaves nothing in the temporary folder.

Folders left by test, mutation and ratchet runs once filled the machine's temporary
folder. Each test here points TMPDIR at a folder of its own, runs the thing, and
looks at what is left.
"""

import os
import pathlib
import signal
import sys
import textwrap

import pytest
from bounded import run_bounded

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _left(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*"))


def test_a_test_run_removes_its_own_temporary_folder(tmp_path):
    """The run's own folder for tmp_path is removed when it ends, and nothing else is made.

    Not pytest's tmp_path_retention_policy: it sweeps the shared pytest-of-<user> folder,
    including folders other projects' running tests are using.
    """
    spare = tmp_path / "tmp"
    spare.mkdir()
    env = {**os.environ, "TMPDIR": str(spare)}
    done = run_bounded(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_disk_cache.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout[-2000:]
    assert _left(spare) == [], f"left in the temporary folder: {_left(spare)}"


# Measures main in a copy, and is stopped the way CI cancels a job, while installing it.
STOPPED_WHILE_MEASURING = textwrap.dedent(
    """
    import importlib.util, os, pathlib, signal, subprocess, sys
    spec = importlib.util.spec_from_file_location("ratchet", sys.argv[1])
    ratchet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ratchet)

    def run(*command, cwd=None, env=None):
        if command[:2] == ("git", "checkout"):
            (pathlib.Path(cwd) / "a-file").write_text("the copy of main")
        elif command[:2] == ("uv", "sync"):
            os.kill(os.getpid(), signal.SIGTERM)
        return subprocess.CompletedProcess(command, 0, "0" * 40, "")

    ratchet._run = run
    ratchet.stop_cleanly()
    ratchet.measure_at("main")
    """
)


def test_a_ratchet_stopped_from_outside_removes_what_it_made(tmp_path):
    spare = tmp_path / "tmp"
    spare.mkdir()
    env = {**os.environ, "TMPDIR": str(spare)}
    done = run_bounded(
        [sys.executable, "-c", STOPPED_WHILE_MEASURING, str(ROOT / "scripts/ratchet.py")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0, "it was stopped, so it must not report success"
    assert _left(spare) == [], f"left in the temporary folder: {_left(spare)}"


STOPS_ITSELF = textwrap.dedent(
    """
    import os, signal, time


    def test_it(tmp_path):
        (tmp_path / "half-done").write_text("x")
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)
    """
)


def test_a_test_run_stopped_from_outside_removes_its_folder(tmp_path):
    """CI cancels a job with SIGTERM; the run must still remove what it made."""
    project, spare = tmp_path / "project", tmp_path / "tmp"
    (project / "tests").mkdir(parents=True)
    spare.mkdir()
    (project / "tests/conftest.py").write_text((ROOT / "tests/conftest.py").read_text())
    (project / "tests/test_stop.py").write_text(STOPS_ITSELF)
    done = run_bounded(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(project), "tests"],
        cwd=project,
        env={**os.environ, "TMPDIR": str(spare)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode != 0, "a stopped run must not report success"
    assert _left(spare) == [], f"left in the temporary folder: {_left(spare)}"


def test_a_second_stop_cannot_cut_the_cleanup_short():
    """GitHub sends SIGINT and then SIGTERM; the second must not stop the cleanup the first began."""
    import importlib.util  # noqa: PLC0415

    spec = importlib.util.spec_from_file_location("conftest_under_test", ROOT / "tests/conftest.py")
    guards = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guards)
    for s in guards.STOPS:  # the run this test is in was set up by the same conftest
        assert getattr(signal.getsignal(s), "__name__", "") == "_stopped", f"{s!r} would not unwind"
    kept = {s: signal.getsignal(s) for s in guards.STOPS}
    try:
        with pytest.raises(KeyboardInterrupt):
            guards._stopped(signal.SIGINT, None)  # noqa: SLF001 - GitHub's first stop
        assert all(signal.getsignal(s) is signal.SIG_IGN for s in guards.STOPS)
    finally:
        for s, handler in kept.items():
            signal.signal(s, handler)
