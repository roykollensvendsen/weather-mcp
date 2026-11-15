"""Guards on a whole test run: what it may change, and what it may leave behind.

A run fails if a test changed the rule check's real recovery file.

`scripts/mutate.py` keeps the file it is mutating there while the suite runs. A
test that ran the runner without its own `RECOVERY` would overwrite or remove it,
and in the middle of a mutation run the original would be lost. Proven by
`tests/test_real_recovery_file_is_guarded.py`.
"""

import pathlib
import shutil
import signal
import tempfile

import pytest

ROOT = pathlib.Path(__file__).parent.parent
RECOVERY = ROOT / "scripts/.mutate-recovery.json"
BEFORE = pytest.StashKey[bytes | None]()


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


#: A folder of this run's own for tmp_path, removed when the run ends. pytest's own folders
#: under pytest-of-<user> are kept after a run, and the mutation check starts one per rule.
#: Its sweeping option would not do either: that folder is shared with other projects' runs.
OWN_TEMP = pytest.StashKey[pathlib.Path]()


def _stopped(_signum: int, _frame: object) -> None:
    """A stop from outside, such as CI cancelling the job, ends the run like Ctrl-C does."""
    raise KeyboardInterrupt


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp is None:
        own = pathlib.Path(tempfile.mkdtemp(prefix="weather-mcp-tests-"))
        config.stash[OWN_TEMP] = own
        config.option.basetemp = own / "run"
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, _stopped)


def pytest_unconfigure(config: pytest.Config) -> None:
    own = config.stash.get(OWN_TEMP, None)
    if own is not None:
        # RULE: a test run removes its own temporary folder
        shutil.rmtree(own, ignore_errors=True)
