"""A stopped mutation run puts the source back, and one run at a time holds the checkout.

Checklist points 5 and 6 (new-plugin-v8.md), copied from easee-mcp's fe2b8c8. The stops
are sent to a real process, since a test that only looks at the installed handlers would
pass a handler that never puts anything back.
"""

import fcntl
import importlib.util
import json
import os
import pathlib
import signal
import subprocess
import sys
import textwrap

import pytest
from bounded import WITHIN, line_within

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture
def mutate():
    spec = importlib.util.spec_from_file_location("mutate_stops_under_test", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.check_the_package = lambda: None  # a scratch checkout has no package of its own
    return module


def _one_rule(tmp_path, *, left_mutated=False):
    """A scratch checkout with one rule's row; optionally as a killed run left it."""
    root = tmp_path / "checkout"
    source = root / "src/pkg/core.py"
    source.parent.mkdir(parents=True)
    source.write_text("x = 2\n" if left_mutated else "x = 1\n")
    rows = root / "scripts/mutations/src/pkg/core.py"
    rows.mkdir(parents=True)
    (rows / "a-rule.toml").write_text(
        '[[rule]]\nname = "a rule"\nfile = "src/pkg/core.py"\nfind = "x = 1"\nreplace = "x = 2"\n'
    )
    if left_mutated:
        kept = {"file": "src/pkg/core.py", "original": "x = 1\n", "mutated": "x = 2\n"}
        (root / "scripts/.mutate-recovery.json").write_text(json.dumps(kept))
    return root, source


def _point_at(monkeypatch, mutate, root, *argv):
    monkeypatch.setattr(mutate.sys, "argv", ["mutate.py", *argv])
    monkeypatch.setattr(mutate, "ROOT", root)
    monkeypatch.setattr(mutate, "ROWS", root / "scripts/mutations")
    monkeypatch.setattr(mutate, "RECOVERY", root / "scripts/.mutate-recovery.json")
    suites = []
    monkeypatch.setattr(mutate, "run_suite", lambda: suites.append(1) or (1, ["test_a_rule"]))
    return suites


def test_one_mutation_run_per_checkout(tmp_path, monkeypatch, mutate):
    """A second run would repair the first one's live mutation, and both would measure nonsense."""
    root, source = _one_rule(tmp_path, left_mutated=True)
    suites = _point_at(monkeypatch, mutate, root)
    first = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(first, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match="already running") as refused:
            mutate.main()
    finally:
        os.close(first)
    assert "pgrep -af mutate.py" in str(refused.value)  # how to find the run holding it
    assert source.read_text() == "x = 2\n"  # the first run's mutation, untouched
    assert (root / "scripts/.mutate-recovery.json").exists()
    assert suites == []


class _Pipe:
    """Output that, like a pipe in CI, shows only what has been flushed."""

    def __init__(self):
        self.held, self.shown = "", ""

    def write(self, text):
        self.held += text
        return len(text)

    def flush(self):
        self.shown, self.held = self.shown + self.held, ""


def test_a_mutation_run_names_each_rule_before_it_tests_it(tmp_path, monkeypatch, mutate):
    """The name must be out of the process, not in its buffer, by the time the suite starts.

    In CI the output is a pipe, which Python holds back until it is full. A run that hung on
    one rule left nothing in the log to say which, and its result line has to get out as well.
    """
    root, _ = _one_rule(tmp_path)
    _point_at(monkeypatch, mutate, root)
    pipe, seen = _Pipe(), []
    monkeypatch.setattr(mutate.sys, "stdout", pipe)
    monkeypatch.setattr(mutate, "run_suite", lambda: seen.append(pipe.shown) or (1, ["test_a_rule"]))
    mutate.main()
    assert "testing  a rule" in seen[0]
    assert "KILLED   a rule: 1" in pipe.shown


def test_a_repair_only_run_only_repairs(tmp_path, monkeypatch, mutate):
    root, source = _one_rule(tmp_path, left_mutated=True)
    suites = _point_at(monkeypatch, mutate, root, "--repair-only")
    assert mutate.main() == 0
    assert source.read_text() == "x = 1\n"
    assert not (root / "scripts/.mutate-recovery.json").exists()
    assert suites == []


STOPPED_MID_MUTATION = textwrap.dedent(
    """
    import importlib.util, pathlib, sys
    spec = importlib.util.spec_from_file_location("mutate", sys.argv[1])
    mutate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mutate)
    root = pathlib.Path(sys.argv[2])
    mutate.ROOT, mutate.ROWS = root, root / "scripts/mutations"
    mutate.RECOVERY = root / "scripts/.mutate-recovery.json"
    mutate.check_the_package = lambda: None
    put_back = mutate.restore


    def measuring():
        print("measuring", flush=True)
        sys.stdin.readline()
        return 1, ["test_a_rule"]


    def slowed(*args):
        print("cleaning", flush=True)
        sys.stdin.readline()
        return put_back(*args)


    mutate.run_suite, mutate.restore = measuring, slowed
    sys.argv = ["mutate.py"]
    sys.exit(mutate.main())
    """
)


def _stop_mid_mutation(tmp_path, *stops):
    """Start a run, stop it while it measures, and send `stops[1:]` once its cleanup has begun."""
    root, source = _one_rule(tmp_path)
    with subprocess.Popen(
        [sys.executable, "-c", STOPPED_MID_MUTATION, str(ROOT / "scripts/mutate.py"), str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as run:
        try:
            assert line_within(run.stdout, WITHIN) == "testing  a rule\n"
            assert line_within(run.stdout, WITHIN) == "measuring\n"
            assert source.read_text() == "x = 2\n"
            run.send_signal(stops[0])
            began = line_within(run.stdout, WITHIN)
            for each in stops[1:]:
                run.send_signal(each)
            _, err = run.communicate("\n", timeout=WITHIN)
        finally:
            if run.poll() is None:  # a run that never answered: ended here, so leaving waits on nothing
                run.kill()
    left = (root / "scripts/.mutate-recovery.json").exists()
    return began, source.read_text(), left, run.returncode, err


#: How each stop may end the run: Ctrl-C as 130, or as death by SIGINT after an uncaught
#: KeyboardInterrupt; a shell sees 130 either way.
ENDS = {signal.SIGINT: (130, -signal.SIGINT), signal.SIGTERM: (143,), signal.SIGHUP: (129,)}


@pytest.mark.parametrize(
    "signum",
    [signal.SIGINT, signal.SIGTERM, signal.SIGHUP],
    ids=["interrupted", "cancelled", "hung up"],
)
def test_a_stopped_mutation_run_puts_the_source_back(tmp_path, signum):
    """Ctrl-C, a cancelled CI job and a closed terminal each leave the source as it was."""
    began, text, recovery_left, code, err = _stop_mid_mutation(tmp_path, signum)
    assert began == "cleaning\n", err
    assert text == "x = 1\n"
    assert not recovery_left
    assert code in ENDS[signum], err


def test_a_second_stop_cannot_cut_a_mutation_runs_cleanup_short(tmp_path):
    """Ctrl-C, then a SIGTERM while the source is being put back: it is still put back."""
    began, text, recovery_left, code, err = _stop_mid_mutation(tmp_path, signal.SIGINT, signal.SIGTERM)
    assert began == "cleaning\n", err
    assert text == "x = 1\n"
    assert not recovery_left
    assert code in ENDS[signal.SIGINT], err
