"""Each test leaves the stop handlers as it found them.

`scripts/mutate.py` and `scripts/ratchet.py` set handlers for SIGINT, SIGTERM and SIGHUP
when their `main()` runs, and a test that runs one in-process would leave them set for
every test after it. `tests/conftest.py` saves them before each test and puts them back
after. Proven here in a scratch run guarded by this repository's conftest, and by the
same run failing once the conftest's putting back is taken out (easee-mcp's way, at f985eae).
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.parent
#: The line in the conftest that puts each handler back.
PUT_BACK = "        signal.signal(each, handler)\n"

TWO_TESTS = """
import signal

STOPS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
AT_START = {s: signal.getsignal(s) for s in STOPS}


def test_a_changes_them():
    for each in STOPS:
        signal.signal(each, signal.SIG_IGN)


def test_b_finds_them_as_they_were():
    assert {s: signal.getsignal(s) for s in STOPS} == AT_START
"""


def _scratch_run(folder: pathlib.Path, conftest: str) -> subprocess.CompletedProcess[str]:
    (folder / "tests").mkdir()
    (folder / "tests/conftest.py").write_text(conftest)
    (folder / "tests/test_scratch.py").write_text(TWO_TESTS)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(folder), "tests"],
        cwd=folder,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


def test_tests_leave_the_stop_handlers_as_they_found_them(tmp_path: pathlib.Path) -> None:
    done = _scratch_run(tmp_path, (ROOT / "tests/conftest.py").read_text(encoding="utf-8"))
    assert done.returncode == 0, done.stdout
    assert "2 passed" in done.stdout


def test_without_the_putting_back_a_test_finds_another_tests_handlers(tmp_path: pathlib.Path) -> None:
    real = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    assert real.count(PUT_BACK) == 1, "the sabotage no longer finds the line it takes out"
    done = _scratch_run(tmp_path, real.replace(PUT_BACK, "        pass\n"))
    assert "1 failed, 1 passed" in done.stdout, done.stdout
