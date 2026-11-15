"""Checks that hold over the whole test session, not one test.

Each run keeps every temporary file its tests make in one folder of its own: pytest's
folders, anything made with `tempfile`, and anything a program the tests start makes
under $TMPDIR. The run holds a lock on that folder while it lasts, and removes the folder
when it ends. A killed run never gets that far, so the next run removes any such folder
whose lock nobody holds. The lock, not a process number, tells a live run: a sandbox has
process numbers of its own, and they are reused.

pytest's own sweep is not used for this: it works on a folder every project on the machine
shares, and set to keep nothing it removes folders other runs are still using. Proven by
`tests/test_no_temp_left.py`. The way is easee-mcp's, at 242c95a.

A stop from outside, as when CI cancels a job, ends the run like Ctrl-C does, so the
folder is still removed; a second stop is then ignored, so it cannot cut that short.

The run also fails if a test changed the rule check's real recovery file.
`scripts/mutate.py` keeps the file it is mutating there while the suite runs, so a test
that ran the runner without its own `RECOVERY` would lose the original. Proven by
`tests/test_real_recovery_file_is_guarded.py`.
"""

import contextlib
import fcntl
import os
import pathlib
import re
import secrets
import shutil
import signal
import stat
import tempfile
import time
from collections.abc import Callable

import pytest

ROOT = pathlib.Path(__file__).parent.parent
RECOVERY = ROOT / "scripts/.mutate-recovery.json"
BEFORE = pytest.StashKey[bytes | None]()
#: This run's folder, the lock it holds on it, and $TMPDIR and tempfile's folder from before.
RUN = pytest.StashKey[tuple[pathlib.Path, int, str | None, str | None]]()
PREFIX = "weather-mcp-tests-"
NAMED = re.compile(re.escape(PREFIX) + r"\d+")
#: A run's folder is made under this name, locked, and only then given its run name, so a
#: sweep never sees a run's name without its lock held. A run killed in between leaves one.
STARTING = re.compile(re.escape(PREFIX) + r"starting-\w+")
#: How old a folder with no lock held, or none made yet, must be before it counts as left
#: by a killed run. A guess: a run takes well under a second to start and lock its folder,
#: and nothing measured says how long a run killed while starting may sit before then.
STARTING_SECONDS = 3600
LOCK = ".lock"
OPEN_LOCK = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
#: A sweep only opens a lock that is there: one it made would sit in a new run's folder
#: before that run moves in, and the run's rename onto it would then fail.
OPEN_THEIR_LOCK = os.O_RDWR | os.O_NOFOLLOW


def _open_up(place: pathlib.Path) -> None:
    """Give the owner back every right on one folder or file; a link is left alone."""
    if place.is_symlink():
        return
    with contextlib.suppress(OSError):
        place.chmod(place.stat().st_mode | stat.S_IRWXU)


def _writable_again(func: Callable[[str], object], path: str, _exc: object) -> None:
    for place in (pathlib.Path(path).parent, pathlib.Path(path)):
        _open_up(place)
    func(path)


def remove(folder: pathlib.Path) -> None:
    """Delete a run's folder, even where a test took away the rights to read or delete it.

    A plain rmtree that ignores errors leaves such a folder behind without a word.
    The way is kassalapp-mcp's.
    """
    for place, folders, _ in os.walk(folder):
        for name in folders:
            _open_up(pathlib.Path(place) / name)
    shutil.rmtree(folder, onexc=_writable_again)


def start_run(temp: pathlib.Path) -> tuple[pathlib.Path, int]:
    """A new run's folder in `temp`, and the lock this run now holds on it."""
    starting = pathlib.Path(tempfile.mkdtemp(prefix=f"{PREFIX}starting-", dir=temp))
    lock = os.open(starting / LOCK, OPEN_LOCK, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    while True:
        folder = temp / f"{PREFIX}{secrets.randbelow(10**12):012d}"
        try:
            folder.mkdir(mode=0o700)  # claims the name, so the rename cannot replace another's
        except FileExistsError:
            continue
        starting.rename(folder)
        return folder, lock


def _ours_to_look_at(path: pathlib.Path) -> os.stat_result | None:
    """What `path` is, if it is a real folder of this user's named like a run's.

    None when it is not, when it may be starting now, or when another sweep removed it first.
    """
    named, starting = NAMED.fullmatch(path.name), STARTING.fullmatch(path.name)
    if not (named or starting):
        return None
    try:
        found = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.getuid():
        return None
    if starting and time.time() - found.st_mtime < STARTING_SECONDS:
        return None
    return found


def _dead(path: pathlib.Path) -> bool:
    """Whether `path` is a run's folder whose run has ended: ours to look at, and unlocked."""
    found = _ours_to_look_at(path)
    if found is None:
        return False
    try:
        lock = os.open(path / LOCK, OPEN_THEIR_LOCK)
    except FileNotFoundError:
        # No lock yet: a new run's claimed name, or a run killed before it locked. The
        # first look's age is used: another sweep may have removed the folder since.
        return time.time() - found.st_mtime >= STARTING_SECONDS
    except OSError:
        return False
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False  # a run still going holds it
    finally:
        os.close(lock)
    return True


def sweep_dead_runs(temp: pathlib.Path) -> None:
    """Remove the run folders in `temp` that runs which died left; never one a run holds.

    Only a real folder named like a run's, and owned by this user, is ever looked at; a
    link is never followed.
    """
    for path in temp.iterdir() if temp.is_dir() else []:
        if _dead(path):
            # RULE: the folder a dead run left is swept at the next run
            remove(path)


#: The stops that end a run like Ctrl-C. GitHub cancels with SIGINT first, then SIGTERM.
STOPS = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)


def _stopped(_signum: int, _frame: object) -> None:
    """End the run as Ctrl-C does, so its cleanup runs; any further stop is ignored."""
    # RULE: a second stop cannot cut the cleanup short
    for signum in STOPS:
        signal.signal(signum, signal.SIG_IGN)
    raise KeyboardInterrupt


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    for signum in STOPS:
        signal.signal(signum, _stopped)
    if config.option.basetemp:  # a run told where to keep them keeps them there
        return
    before, cached = os.environ.get("TMPDIR"), tempfile.tempdir  # gettempdir() fills tempdir in
    temp = pathlib.Path(tempfile.gettempdir())
    sweep_dead_runs(temp)
    folder, lock = start_run(temp)
    config.stash[RUN] = (folder, lock, before, cached)
    os.environ["TMPDIR"] = str(folder)
    tempfile.tempdir = str(folder)
    # A folder inside it: pytest empties its basetemp first, which would take the lock too.
    config.option.basetemp = str(folder / "pytest")


def pytest_unconfigure(config: pytest.Config) -> None:
    run = config.stash.get(RUN, None)
    if run is None:
        return
    folder, lock, before, cached = run
    if before is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = before
    tempfile.tempdir = cached
    # RULE: a test run removes its own temporary folder
    remove(folder)
    os.close(lock)


def _now() -> bytes | None:
    return RECOVERY.read_bytes() if RECOVERY.is_file() else None


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[BEFORE] = _now()


def pytest_sessionfinish(session: pytest.Session) -> None:
    if _now() != session.config.stash[BEFORE]:
        print(  # noqa: T201
            "\nA test changed scripts/.mutate-recovery.json, the rule check's real recovery file. "
            "A test that runs scripts/mutate.py must point RECOVERY at its own temporary file."
        )
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
