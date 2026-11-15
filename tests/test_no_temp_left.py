"""A run leaves nothing in the shared temporary folder.

The temporary folder is shared by every project on the machine, and one that
only fills up stops every test run there with "Disk quota exceeded". So each
run here cleans up after itself: pytest removes its folders when the session
ends and sweeps those a killed run left. Ported from easee-mcp's tests at 242c95a.

Each test points TMPDIR at a folder of its own and looks inside it afterwards.
"""

import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import types

import pytest

ROOT = pathlib.Path(__file__).parent.parent


def _files_in(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if not p.is_dir())


def _pytest(temp, *tests):
    """Run some of this project's tests, with its own settings, using `temp` as the temporary folder."""
    env = {**os.environ, "TMPDIR": str(temp)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _run_folder(temp, digits="123456789012"):
    folder = temp / f"weather-mcp-tests-{digits}"
    folder.mkdir(parents=True)
    (folder / ".lock").touch()  # a run locks it as it starts; a killed run's lock is free
    (folder / "kept").write_text("a run's folder")
    return folder


def test_the_folder_a_dead_run_left_is_swept_at_the_next_run(tmp_path):
    """A killed run never reaches its own cleanup; nothing holds its lock any more."""
    temp = tmp_path / "temp"
    _run_folder(temp)
    done = _pytest(temp, "tests/test_disk_cache.py")
    assert done.returncode == 0, done.stdout
    assert _files_in(temp) == []


HOLDS_THE_LOCK = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
print("holding", flush=True)
sys.stdin.read()
"""


def test_a_live_runs_folder_is_kept(tmp_path):
    """A run still going holds its folder's lock, whatever its process number looks like from here."""
    temp = tmp_path / "temp"
    live = _run_folder(temp)
    with subprocess.Popen(
        [sys.executable, "-c", HOLDS_THE_LOCK, str(live / ".lock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as holder:
        assert holder.stdout.readline().strip() == "holding"
        done = _pytest(temp, "tests/test_disk_cache.py")
        holder.stdin.close()
    assert done.returncode == 0, done.stdout
    assert _files_in(temp) == [f"{live.name}/.lock", f"{live.name}/kept"]  # untouched


def test_a_link_named_like_a_run_is_left_alone(tmp_path):
    """A link could point anywhere; the sweep never follows one."""
    temp, elsewhere = tmp_path / "temp", tmp_path / "elsewhere"
    temp.mkdir()
    elsewhere.mkdir()
    (elsewhere / "precious").write_text("not a run's")
    (temp / "weather-mcp-tests-123456789012").symlink_to(elsewhere)
    done = _pytest(temp, "tests/test_disk_cache.py")
    assert done.returncode == 0, done.stdout
    assert (temp / "weather-mcp-tests-123456789012").is_symlink()
    assert [p.name for p in elsewhere.iterdir()] == ["precious"]  # not even a lock made there
    assert (elsewhere / "precious").read_text() == "not a run's"


def test_a_tests_temporary_files_go_in_the_runs_own_folder(tmp_path):
    """tmp_path, tempfile and every program a test starts all write inside the run's folder."""
    run = pathlib.Path(os.environ["TMPDIR"])
    assert re.fullmatch(r"weather-mcp-tests-\d+", run.name)
    assert tmp_path.is_relative_to(run)
    assert pathlib.Path(tempfile.gettempdir()) == run
    child = subprocess.run(
        [sys.executable, "-c", "import tempfile; print(tempfile.gettempdir())"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert pathlib.Path(child.stdout.strip()) == run


def test_the_temporary_folder_is_put_back_when_the_run_ends(tmp_path, monkeypatch):
    import conftest  # noqa: PLC0415 - the hooks under test

    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    config = types.SimpleNamespace(option=types.SimpleNamespace(basetemp=None), stash=pytest.Stash())
    conftest.pytest_configure(config)
    assert os.environ["TMPDIR"] != str(tmp_path)
    conftest.pytest_unconfigure(config)
    assert os.environ["TMPDIR"] == str(tmp_path)
    assert tempfile.tempdir is None
    assert list(tmp_path.iterdir()) == []


def test_a_new_runs_folder_is_never_seen_unlocked_under_a_runs_name(tmp_path, monkeypatch):
    """Another run sweeping just then must not take the lock between the folder and its lock."""
    import conftest  # noqa: PLC0415 - the hooks under test

    locked_while_named = []
    real_flock = conftest.fcntl.flock

    def flock(fd, how):
        locked_while_named.append([p.name for p in tmp_path.iterdir() if conftest.NAMED.fullmatch(p.name)])
        return real_flock(fd, how)

    monkeypatch.setattr(conftest.fcntl, "flock", flock)
    folder, lock = conftest.start_run(tmp_path)
    try:
        assert locked_while_named == [[]]
        assert conftest.NAMED.fullmatch(folder.name)
    finally:
        os.close(lock)


def test_a_dead_runs_folder_is_swept_even_where_a_test_shut_it(tmp_path):
    """A folder a test made unreadable would be left silently by a plain rmtree."""
    temp = tmp_path / "temp"
    shut = _run_folder(temp) / "shut"
    shut.mkdir()
    (shut / "inside").write_text("x")
    shut.chmod(0)
    try:
        done = _pytest(temp, "tests/test_disk_cache.py")
    finally:
        if shut.exists():
            shut.chmod(0o700)
    assert done.returncode == 0, done.stdout
    assert _files_in(temp) == []


def _starting(temp, *, hours_old):
    folder = temp / "weather-mcp-tests-starting-abc"
    folder.mkdir(parents=True)
    (folder / "kept").write_text("a run killed while it started")
    then = time.time() - hours_old * 3600
    os.utime(folder, (then, then))
    return folder


def test_a_run_killed_while_it_started_is_swept_once_it_is_old(tmp_path):
    temp = tmp_path / "temp"
    _starting(temp, hours_old=2)
    done = _pytest(temp, "tests/test_disk_cache.py")
    assert done.returncode == 0, done.stdout
    assert _files_in(temp) == []


def test_a_run_that_is_starting_now_is_left_alone(tmp_path):
    temp = tmp_path / "temp"
    young = _starting(temp, hours_old=0)
    done = _pytest(temp, "tests/test_disk_cache.py")
    assert done.returncode == 0, done.stdout
    assert _files_in(temp) == [f"{young.name}/kept"]


def test_another_users_folder_is_never_swept(tmp_path, monkeypatch):
    """A folder named like a run's but owned by someone else is theirs, whatever its lock."""
    import conftest  # noqa: PLC0415 - the hooks under test

    theirs = _run_folder(tmp_path)
    monkeypatch.setattr(conftest.os, "getuid", lambda: theirs.lstat().st_uid + 1)
    conftest.sweep_dead_runs(tmp_path)
    assert (theirs / "kept").exists()


def test_a_runs_folder_not_yet_locked_is_left_alone_and_given_no_lock(tmp_path):
    """Between claiming its name and moving in, a new run's folder has no lock yet."""
    import conftest  # noqa: PLC0415 - the hooks under test

    fresh = tmp_path / "weather-mcp-tests-123456789012"
    fresh.mkdir()
    conftest.sweep_dead_runs(tmp_path)
    assert fresh.is_dir()
    assert list(fresh.iterdir()) == []  # no lock made there, so its rename can still land


def test_an_old_runs_folder_with_no_lock_is_swept(tmp_path):
    import conftest  # noqa: PLC0415 - the hooks under test

    old = tmp_path / "weather-mcp-tests-123456789012"
    old.mkdir()
    then = time.time() - 2 * 3600
    os.utime(old, (then, then))
    conftest.sweep_dead_runs(tmp_path)
    assert not old.exists()


def test_a_folder_another_sweep_removed_first_is_passed_over(tmp_path, monkeypatch):
    """Two runs may sweep at once; the one that comes second finds the folder already gone."""
    import conftest  # noqa: PLC0415 - the hooks under test

    gone = tmp_path / "weather-mcp-tests-123456789012"
    gone.mkdir()
    real_open = conftest.os.open

    def open_after_the_other_sweep(path, *args, **kwargs):
        if gone.exists():
            gone.rmdir()  # the other sweep removes it after this one first looked
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(conftest.os, "open", open_after_the_other_sweep)
    conftest.sweep_dead_runs(tmp_path)  # passes over it, rather than fail the run
    assert not gone.exists()
