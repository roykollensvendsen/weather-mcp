"""A stopped ratchet passes the stop to the step it runs, once, and waits for it.

Checklist point 8 (new-plugin-v8.md, at 9b70c77580be), in dreame-mcp #45's form. The
ratchet's step is a mutation run or a suite. Stopped, it must be told with one Ctrl-C and
then waited for, so a mutation run can put its line back and a suite can remove its files.
A second Ctrl-C would make pytest cut its own cleanup short.

Each test runs a stand-in ratchet, the real `_run` with the real `stop_cleanly`, around a
stand-in step, in its own process group as a terminal gives a command.
"""

import contextlib
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

import pytest
from bounded import WITHIN

ROOT = pathlib.Path(__file__).parent.parent

#: Stands in for the ratchet: runs a command through its _run, and can be stopped.
RATCHET = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ratchet", sys.argv[1])
ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ratchet)
ratchet.stop_cleanly()
if sys.argv[2] == "muted":  # as the mutation that switches the stop off leaves it
    ratchet.subprocess.Popen.send_signal = lambda step, signum: None
ratchet._run(*sys.argv[4:], "-c", sys.argv[3])
"""

#: How the stand-in starts its step: straight, or through uv, as the ratchet starts its own.
STRAIGHT = (sys.executable,)
THROUGH_UV = ("uv", "run", "--no-project", "python")

#: Stands in for a mutation run: says it is going, and on Ctrl-C puts its line back. Every
#: Ctrl-C it gets is counted: a second one would make pytest cut its own cleanup short.
STEP = """
import os, pathlib, signal, sys, time
marks = pathlib.Path({marks!r})
(marks / "group").write_text(str(os.getpgrp()))
def put_back(*_):
    with open(marks / "put-back", "a") as told:
        told.write("x")
    time.sleep(1)  # room for a second Ctrl-C to arrive and be counted
    sys.exit(130)
signal.signal(signal.SIGINT, put_back)
(marks / "going").write_text(f"{os.getpid()} {os.getppid()}")  # this step, and what started it
time.sleep(120)
"""


def _wait_for(path: pathlib.Path) -> None:
    for _ in range(600):
        if path.exists() and path.read_text():
            return
        time.sleep(0.05)
    msg = f"{path.name} never appeared"
    raise AssertionError(msg)


def _stop_while_the_step_runs(tmp_path, stop, starts=STRAIGHT, *, muted=False, patience=60):
    marks = tmp_path / "marks"
    marks.mkdir()
    step = STEP.replace("{marks!r}", repr(str(marks)))
    mode = "muted" if muted else "-"
    stand_in = subprocess.Popen(
        [sys.executable, "-c", RATCHET, str(ROOT / "scripts/ratchet.py"), mode, step, *starts],
        start_new_session=True,  # its own process group, as a terminal gives a command
    )
    code = None
    try:
        _wait_for(marks / "going")
        stop(stand_in)
        with contextlib.suppress(subprocess.TimeoutExpired):  # a muted stop never lets it end
            code = stand_in.wait(timeout=patience)
    finally:
        if stand_in.poll() is None:
            os.killpg(stand_in.pid, signal.SIGKILL)
        _end_what_it_started(marks)
    (marks / "terminal-group").write_text(str(stand_in.pid))
    return code, marks


def _end_what_it_started(marks):
    """End the step and what started it, if either still runs, and wait until both are gone.

    They run in a session of their own, which the stand-in's group kill never reaches. Each
    is ended by its own pid, never by group, and only while its command still names this
    test's folder, so a pid the system has since given to another process is left alone.
    """
    going = marks / "going"
    pids = [int(pid) for pid in going.read_text().split()] if going.exists() else []
    for pid in pids:
        with contextlib.suppress(OSError):
            if str(marks) in pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace"):
                os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 10
    while any(_running(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)


def test_a_stopped_quality_run_stops_its_step_and_waits_for_it(tmp_path):
    """A cancelled CI job: the step is told with Ctrl-C, not killed outright, and waited for."""
    code, marks = _stop_while_the_step_runs(tmp_path, lambda p: p.send_signal(signal.SIGTERM))
    assert code == 128 + signal.SIGTERM
    assert (marks / "put-back").read_text() == "x"


def test_a_quality_step_hears_terminal_stops_only_through_the_ratchet(tmp_path):
    """A terminal's Ctrl-C goes to the whole process group it gave the ratchet.

    Two Ctrl-Cs that arrive together are one to Python, so counting alone can miss the
    second: the step must also sit outside the group the terminal's Ctrl-C goes to.
    """
    code, marks = _stop_while_the_step_runs(tmp_path, lambda p: os.killpg(p.pid, signal.SIGINT))
    assert code != 0
    assert (marks / "group").read_text() != (marks / "terminal-group").read_text()
    assert (marks / "put-back").read_text() == "x"  # once, not twice


@pytest.mark.skipif(
    shutil.which("uv") is None and not os.environ.get("CI"),
    reason="needs uv, which the ratchet starts its steps through (in CI, its absence fails instead)",
)
@pytest.mark.parametrize("stop", [signal.SIGTERM, signal.SIGINT], ids=["kill", "ctrl-c"])
def test_a_stopped_ratchet_tells_the_python_under_uv_once(tmp_path, stop):
    """The ratchet starts its steps through uv, and uv passes a Ctrl-C on to its own child.

    Sent to uv's whole process group instead, the Ctrl-C would reach that child twice.
    """
    # In CI the proof must not drop out unseen: there a missing uv is a failure, not a skip.
    if shutil.which("uv") is None:
        pytest.fail("CI has no uv, so the proof that a stopped ratchet tells uv's child once cannot run")

    def send(stand_in):
        if stop == signal.SIGINT:
            os.killpg(stand_in.pid, stop)  # a terminal's Ctrl-C, to the ratchet's group
        else:
            stand_in.send_signal(stop)

    code, marks = _stop_while_the_step_runs(tmp_path, send, THROUGH_UV)
    assert code != 0
    assert (marks / "put-back").read_text() == "x"  # once, not twice


#: Stands in for a suite: says it is going, waits until the ratchet is gone, then writes a
#: lot, as pytest's summary does, and only then marks itself finished.
OUTLIVES = """
import os, pathlib, sys, time
marks = pathlib.Path({marks!r})
(marks / "going").write_text(str(os.getpid()))
while not (marks / "ratchet-gone").exists():
    time.sleep(0.05)
print("x" * 1_000_000, flush=True)
print("y" * 1_000_000, file=sys.stderr, flush=True)
(marks / "finished").touch()
"""


def test_a_step_outlives_a_ratchet_killed_with_kill_9(tmp_path):
    """A hung ratchet is ended with kill -9, and its step must still finish its cleanup.

    Writing into a pipe whose reader is dead, it would die mid-mutation instead.
    """
    marks = tmp_path / "marks"
    marks.mkdir()
    step = OUTLIVES.replace("{marks!r}", repr(str(marks)))
    stand_in = subprocess.Popen(
        [sys.executable, "-c", RATCHET, str(ROOT / "scripts/ratchet.py"), "-", step, *STRAIGHT]
    )
    pid = None
    try:
        _wait_for(marks / "going")
        for _ in range(600):
            if pid := (marks / "going").read_text():
                break
            time.sleep(0.05)
        pid = int(pid)
        stand_in.kill()
        stand_in.wait(timeout=WITHIN)
        (marks / "ratchet-gone").touch()
        for _ in range(600):
            if (marks / "finished").exists() or not pathlib.Path(f"/proc/{pid}").exists():
                break
            time.sleep(0.05)
        assert (marks / "finished").exists(), "the step died once the ratchet was gone"
    finally:
        if stand_in.poll() is None:
            stand_in.kill()
        if pid and pathlib.Path(f"/proc/{pid}").exists():
            os.kill(pid, signal.SIGKILL)


def _running(pid):
    """Whether process `pid` is still running, rather than ended or only a zombie left to reap."""
    try:
        state = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return False
    return state != "Z"


def test_a_process_that_ends_while_it_is_read_counts_as_not_running(monkeypatch):
    """Linux says "no such process" when a process ends between finding its file and reading it."""

    def ended(*_args, **_kwargs):
        raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(pathlib.Path, "read_text", ended)
    assert not _running(os.getpid())


@pytest.mark.skipif(
    not pathlib.Path("/proc").is_dir(),
    reason="reads each process's state from /proc; without it, nothing would look left running",
)
@pytest.mark.skipif(
    shutil.which("uv") is None and not os.environ.get("CI"),
    reason="needs uv, which the ratchet starts its steps through (in CI, its absence fails instead)",
)
def test_a_muted_stop_leaves_no_step_running_under_uv(tmp_path):
    """With the stop switched off, as a mutation leaves it, the step never ends by itself.

    It and its uv run in a session of their own, so the test must end them. Left running,
    the pair holds uv's cache lock for every later uv run on the machine (the analyst, 16.11).
    """
    if shutil.which("uv") is None:
        pytest.fail("CI has no uv, so the proof that a muted stop leaves nothing running cannot run")
    _, marks = _stop_while_the_step_runs(
        tmp_path, lambda p: p.send_signal(signal.SIGTERM), THROUGH_UV, muted=True, patience=2
    )
    assert not (marks / "put-back").exists()  # the stop was muted: the step was never told
    pids = [int(pid) for pid in (marks / "going").read_text().split()]
    deadline = time.monotonic() + 10
    while any(_running(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.05)
    left = [pid for pid in pids if _running(pid)]
    assert not left, f"the step and its uv were left running: {left}"
