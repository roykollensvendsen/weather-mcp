"""The checks measure this checkout's own package, never one installed from another.

Checklist point 9 (new-plugin-v8.md, at 9b70c77580be), copied from easee-mcp's a857593.
Two worktrees sharing one venv import whichever one installed the package last, so every
rule would be measured against the other one's code (dreame).
"""

import importlib.util
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_package_check", ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mutate():
    return _load("mutate")


@pytest.fixture
def ratchet():
    return _load("ratchet")


def _two_checkouts(tmp_path):
    """Two checkouts, each holding a package of the same name."""
    here, other = tmp_path / "here", tmp_path / "other"
    for root in (here, other):
        (root / "src/pkg").mkdir(parents=True)
        (root / "src/pkg/__init__.py").write_text("")
    return here, other


def test_a_mutation_run_refuses_a_package_from_another_checkout(tmp_path, monkeypatch, mutate):
    """A venv shared with another worktree measures that worktree's code, and every rule looks the same."""
    here, other = _two_checkouts(tmp_path)
    monkeypatch.setattr(mutate, "ROOT", here)
    monkeypatch.setenv("PYTHONPATH", str(other / "src"))
    with pytest.raises(SystemExit, match="uv sync") as refused:
        mutate.check_the_package()
    assert str(other / "src/pkg") in str(refused.value)
    assert str(here / "src") in str(refused.value)


def test_a_package_from_this_checkout_is_measured(tmp_path, monkeypatch, mutate):
    here, _ = _two_checkouts(tmp_path)
    monkeypatch.setattr(mutate, "ROOT", here)
    monkeypatch.setenv("PYTHONPATH", str(here / "src"))
    mutate.check_the_package()


def test_a_mutation_run_checks_the_package_before_it_measures(tmp_path, monkeypatch, mutate):
    (tmp_path / "mutations").mkdir()
    monkeypatch.setattr(mutate, "ROOT", tmp_path)
    monkeypatch.setattr(mutate, "ROWS", tmp_path / "mutations")
    monkeypatch.setattr(mutate, "RECOVERY", tmp_path / ".mutate-recovery.json")
    monkeypatch.setattr(mutate.sys, "argv", ["mutate.py"])
    measured = []
    monkeypatch.setattr(mutate, "run_suite", lambda: measured.append(1) or (0, []))

    def refused():
        msg = "from another checkout"
        raise SystemExit(msg)

    monkeypatch.setattr(mutate, "check_the_package", refused)
    with pytest.raises(SystemExit, match="another checkout"):
        mutate.main()
    assert measured == []


def _package_found_at(monkeypatch, ratchet, where, returncode=0):
    asked = []

    def run(*command, **_):
        asked.append(command)
        return subprocess.CompletedProcess(command, returncode, f"{where}\n", "No module named weather_mcp")

    monkeypatch.setattr(ratchet, "_run", run)
    return asked


def test_a_quality_run_refuses_a_package_from_another_checkout(monkeypatch, tmp_path, ratchet):
    """Measured from another worktree's source, the levels would be that worktree's."""
    other = tmp_path / "other/src/weather_mcp/__init__.py"
    asked = _package_found_at(monkeypatch, ratchet, other)
    with pytest.raises(SystemExit, match="uv sync") as refused:
        ratchet.check_the_package()
    assert str(other.parent) in str(refused.value)
    assert str(ratchet.SOURCE) in str(refused.value)
    assert asked == [("uv", "run", "python", "-c", "import weather_mcp; print(weather_mcp.__file__)")]


def test_a_quality_run_measures_a_package_from_its_own_checkout(monkeypatch, ratchet):
    _package_found_at(monkeypatch, ratchet, ratchet.PACKAGE / "__init__.py")
    ratchet.check_the_package()


def test_a_package_that_will_not_import_is_refused_too(monkeypatch, ratchet):
    _package_found_at(monkeypatch, ratchet, "", returncode=1)
    with pytest.raises(SystemExit, match="No module named weather_mcp"):
        ratchet.check_the_package()


def test_a_quality_run_checks_the_package_before_it_measures(monkeypatch, ratchet):
    def refused():
        msg = "from another checkout"
        raise SystemExit(msg)

    ran = []
    monkeypatch.setattr(ratchet, "check_the_package", refused)
    monkeypatch.setattr(ratchet, "_run", lambda *c, **_: ran.append(c))
    with pytest.raises(SystemExit, match="another checkout"):
        ratchet.measure()
    assert ran == []
