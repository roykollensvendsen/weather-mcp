"""Nothing committed says where the owner lives."""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "scripts"))

import private_data_scan

# Built at run time throughout, so this file does not itself hold what it forbids.
NONE = pathlib.Path("/nonexistent/none.toml")


def test_a_home_network_address_is_never_committed():
    for address in (".".join(p) for p in (("10", "0", "0", "7"), ("192", "168", "1", "50"))):
        assert private_data_scan.offences(f"bridge at http://{address}:8000", set()), address


def test_a_street_address_is_never_committed():
    assert private_data_scan.offences("home in " + "Storgata" + " 12", set())
    assert private_data_scan.offences("Kirke" + "veien 3B", set())


def test_coordinates_more_exact_than_two_decimals_are_never_committed():
    assert private_data_scan.offences("home = " + "59.91" + "38, 10.75" + "22", set())
    assert private_data_scan.offences("lat = " + "59.91" + "38", set())
    assert private_data_scan.offences('"lat": "' + "63.43" + '05"', set())
    assert private_data_scan.offences("home = 59.91, 10.75\nlat = 59.91", set()) == []


def test_only_the_tests_own_made_up_points_are_allowed():
    assert private_data_scan.offences("place(61.00412, 9.00377)", set()) == []
    assert private_data_scan.offences("place(61.00" + "413, 9.00377)", set())


def test_a_word_from_the_private_list_is_never_committed(tmp_path):
    words = tmp_path / "private.toml"
    words.write_text('words = ["Nabogarden", "ab"]\n')
    found, _ = private_data_scan.private_values(words, NONE)
    # A word too short to be told from ordinary text is left out.
    assert found == {"Nabogarden"}
    assert private_data_scan.offences("near nabogarden", found)


def _home(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text('contact = "x"\n[home]\nname = "Heimstad"\nlat = 62.3456\nlon = 7.891\n')
    return private_data_scan.private_values(NONE, config)


def test_homes_name_is_never_committed(tmp_path):
    found, _ = _home(tmp_path)
    assert private_data_scan.offences("the weather in heimstad", found)


def test_the_home_point_on_one_line_is_refused(tmp_path):
    found, home = _home(tmp_path)
    assert home == ("62.35", "7.89")
    assert private_data_scan.offences("params lat=62.35 lon=7.89", found, home)
    assert private_data_scan.offences("lat 62.35\nlon 7.89", found, home) == []


def test_ordinary_text_and_documentation_addresses_are_allowed():
    text = "Bergen and Moen, 192.0.2.10, version 1.2.3.4, 26.90 kroner, lat = 0.00, 61.00, 9.00"
    assert private_data_scan.offences(text, set()) == []


def _clean_run(*flags):
    return private_data_scan.main([*flags, "--words", str(NONE), "--config", str(NONE)])


def test_the_tracked_tree_is_clean():
    assert _clean_run("--tracked") == 0


def test_the_history_is_clean():
    assert _clean_run("--history") == 0


def test_a_broken_private_list_refuses_the_commit_and_says_why(tmp_path, capsys):
    words = tmp_path / "private.toml"
    words.write_text('words = ["Nabogarden"\n', encoding="utf-8")
    assert private_data_scan.main(["--tracked", "--words", str(words), "--config", str(NONE)]) == 1
    said = capsys.readouterr().err
    assert "private.toml can't be read" in said
    assert "Nabogarden" not in said


def test_a_private_list_without_a_list_of_words_refuses_the_commit(tmp_path, capsys):
    words = tmp_path / "private.toml"
    words.write_text('words = "Nabogarden"\n', encoding="utf-8")
    assert private_data_scan.main(["--tracked", "--words", str(words), "--config", str(NONE)]) == 1
    assert "a list of words" in capsys.readouterr().err


def test_a_broken_private_list_refuses_the_commit_never_skips_the_check(tmp_path, capsys):
    # Neither a folder in the list's place nor a link to a file moved away may read
    # as "no list", which would check nothing. The config is held to the same.
    folder = tmp_path / "folder" / "private.toml"
    folder.mkdir(parents=True)
    link = tmp_path / "link" / "config.toml"
    link.parent.mkdir()
    link.symlink_to(tmp_path / "moved-away.toml")
    assert private_data_scan.main(["--tracked", "--words", str(folder), "--config", str(NONE)]) == 1
    assert "private.toml can't be read" in capsys.readouterr().err
    assert private_data_scan.main(["--tracked", "--words", str(NONE), "--config", str(link)]) == 1
    assert "config.toml can't be read" in capsys.readouterr().err


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_a_private_list_nobody_may_read_refuses_the_commit(tmp_path, capsys):
    words = tmp_path / "private.toml"
    words.write_text('words = ["Nabogarden"]\n', encoding="utf-8")
    words.chmod(0)
    try:
        assert private_data_scan.main(["--tracked", "--words", str(words), "--config", str(NONE)]) == 1
    finally:
        words.chmod(0o600)
    said = capsys.readouterr().err
    assert "private.toml can't be read" in said
    assert "Traceback" not in said
