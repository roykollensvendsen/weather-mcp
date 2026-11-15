#!/usr/bin/env python3
"""Refuse a commit that would publish where the owner lives.

This repository is public. Nothing in it may name the owner's home, their
street or their town. The checks, on every file given (by default the files
staged for commit), or on the whole history:

- no home-network address: a private IPv4 address (examples use 192.0.2.x);
- no street address, such as a Norwegian street name followed by a number;
- no coordinates in Norway more exact than two decimals, as a pair or as
  ``lat = ...``, except the made-up points the tests use;
- not home itself: its name, or its latitude and longitude within three lines
  of each other, read from the owner's ``~/.config/weather-mcp/config.toml``.
  Home's latitude alone is not refused: it is half a point, and a two-decimal
  number on its own matches too much ordinary text;
- no word from the owner's private list.

The private list is ``~/.config/weather-mcp/private.toml``, holding
``words = ["...", ...]``. It and the config live outside the repository, so
neither is ever published. A config or list that exists but cannot be read
refuses the commit, rather than checking nothing.

What is found is reported by kind and line, never quoted, since the report may
land in a public log.

    python3 scripts/private_data_scan.py            # the staged files (pre-commit)
    python3 scripts/private_data_scan.py --tracked  # every tracked file
    python3 scripts/private_data_scan.py --history  # every commit on every branch
"""

from __future__ import annotations

import argparse
import math
import os
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORDS = pathlib.Path("~/.config/weather-mcp/private.toml")
CONFIG = pathlib.Path("~/.config/weather-mcp/config.toml")
#: Shorter words would match ordinary text.
MIN_WORD = 4

PRIVATE_IPV4 = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\d.])"
)
STREET = re.compile(
    r"\b[A-ZÆØÅ][a-zæøå]+(?:gata|gaten|gate|veien|vegen|vei|veg|torget|plassen|allé|alleen)"
    r"\s+\d{1,4}[A-Za-z]?\b"
)
#: Norway lies within about 57-72 north and 4-32 east.
COORDINATES = re.compile(r"\b(?:5[7-9]|6\d|7[0-2])\.\d{3,}\s*,\s*(?:[4-9]|[12]\d|3[0-2])\.\d{3,}\b")
LATITUDE = re.compile(r"\blat\w*\"?\s*[=:]\s*\"?((?:5[7-9]|6\d|7[0-2])\.\d{3,})")
#: The made-up numbers the tests use, near 61.00 N 9.00 E on purpose: two places in
#: tests/fakes.py, a latitude too exact for MET in tests/test_cache.py, and a phone's
#: position in tests/test_weather_now.py. They are in the history, which cannot be
#: rewritten, so they are named here rather than hidden.
MADE_UP = frozenset({"61.00412", "9.00377", "61.013", "9.012", "61.00001", "61.3712", "9.4249"})
NUMBER = re.compile(r"\d+\.\d+")


class BrokenListError(ValueError):
    """The private list or the config exists but can't be used, so it would go unchecked."""


def _toml(path: pathlib.Path) -> dict[str, object] | None:
    """A local file's contents; None only when nothing is in its place."""
    # Anything in the file's place counts: only a missing one means "none".
    # A link to a file that was moved away is there too, so lexists, not exists.
    # RULE: a broken private list refuses the commit never skips the check
    if not os.path.lexists(path):
        return None
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
        # The parser's own message is left out: it may quote a private word.
        message = f"{path.name} can't be read as a TOML file"
        raise BrokenListError(message) from error


#: Home's latitude and longitude, each in every way it could be written at two decimals.
Home = tuple[frozenset[str], frozenset[str]]
#: Home's latitude and longitude count together when this many lines apart or fewer, as in
#: a pasted config, where ``lat`` and ``lon`` are on lines of their own.
NEAR = 2


def _forms(degrees: float) -> frozenset[str]:
    """Two decimals, rounded and cut off, with a decimal point or a decimal comma."""
    numbers = {f"{degrees:.2f}", f"{math.trunc(degrees * 100) / 100:.2f}"}
    return frozenset(numbers | {n.replace(".", ",") for n in numbers})


def private_values(words: pathlib.Path, config: pathlib.Path) -> tuple[set[str], Home | None]:
    """The owner's private words, home's name among them, and home's point."""
    out: set[str] = set()
    listed = (_toml(words) or {}).get("words", [])
    if not isinstance(listed, list):
        message = f"{words.name} must hold words = [...], a list of words"
        raise BrokenListError(message)
    out |= {w for w in listed if isinstance(w, str) and len(w) >= MIN_WORD}
    home = (_toml(config) or {}).get("home")
    point = None
    if isinstance(home, dict):
        name = home.get("name")
        if isinstance(name, str) and len(name) >= MIN_WORD:
            out.add(name)
        lat, lon = home.get("lat"), home.get("lon")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            point = (_forms(lat), _forms(lon))
    return out, point


def offences(text: str, private: set[str], home: Home | None = None) -> list[str]:
    """What in ``text`` would say where the owner lives, by kind only."""
    found = [f"line {_line(text, m.start())}: a home-network address" for m in PRIVATE_IPV4.finditer(text)]
    found += [f"line {_line(text, m.start())}: a street address" for m in STREET.finditer(text)]
    found += [
        f"line {_line(text, m.start())}: exact coordinates"
        for m in COORDINATES.finditer(text)
        # RULE: only the tests own made up points are allowed
        if not set(NUMBER.findall(m.group())) <= MADE_UP
    ]
    found += [
        f"line {_line(text, m.start())}: an exact latitude"
        for m in LATITUDE.finditer(text)
        if m.group(1) not in MADE_UP
    ]
    lowered = text.lower()
    for value in private:
        at = lowered.find(value.lower())
        if at >= 0:
            found.append(f"line {_line(text, at)}: a private word")
    if home is not None:
        found += [f"line {number}: home's point" for number in _home_lines(text, home)]
    return found


def _home_lines(text: str, home: Home) -> list[int]:
    """Each line holding home's latitude with its longitude on it or near it."""
    lines = text.splitlines()
    lats, lons = ([i for i, line in enumerate(lines) if any(f in line for f in forms)] for forms in home)
    # RULE: the home point within three lines is refused
    return [i + 1 for i in lats if any(abs(i - j) <= NEAR for j in lons)]


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def _git(*args: str) -> str:
    command = ["git", *args]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8", check=True)  # noqa: S603
    return done.stdout


def _texts(*, tracked: bool, history: bool) -> list[tuple[str, str]]:
    """Each place to scan, as (what it is, its text)."""
    if history:
        # What lands on the branch: other branches here, such as one under review with
        # its own made-up numbers, are scanned on their own branch, by their own list.
        # RULE: the history scanned is what lands on the branch
        return [("the history", _git("log", "-p", "HEAD", "--no-color", "--format=commit %H%n%B"))]
    if not tracked:
        # What the commit will hold is the staged copy, which may differ from the file on disk.
        # RULE: a commit is scanned as staged
        staged = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines()
        return [(name, text) for name in staged if (text := _staged(name)) is not None]
    out = []
    for name in _git("ls-files").splitlines():
        try:
            out.append((name, (ROOT / name).read_text(encoding="utf-8")))
        except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError):
            continue
    return out


def _staged(name: str) -> str | None:
    """The staged copy of a file, or None when it is not text."""
    command = ["git", "show", f":{name}"]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, check=True)  # noqa: S603
    try:
        return done.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main(argv: list[str] | None = None) -> int:
    """Scan the staged files, every tracked file, or the history; 1 when anything is found."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--tracked", action="store_true", help="scan every tracked file")
    parser.add_argument("--history", action="store_true", help="scan every commit on every branch")
    parser.add_argument("--words", default=str(WORDS), help=f"the private list (default {WORDS})")
    parser.add_argument("--config", default=str(CONFIG), help=f"where home is set (default {CONFIG})")
    args = parser.parse_args(argv)
    words, config = pathlib.Path(args.words).expanduser(), pathlib.Path(args.config).expanduser()
    # A clean result must not read as "home was checked" when there was nothing to check it by.
    for path, what, kind in ((config, "home", "config"), (words, "private words", "list")):
        # RULE: a missing config or list is said plainly
        if not os.path.lexists(path):  # a link to a moved file counts as there
            sys.stderr.write(f"{what} not checked: no {kind} at {path}\n")
    try:
        private, home = private_values(words, config)
    except BrokenListError as error:
        # Refused rather than skipped: a commit checked without the list could publish a word from it.
        sys.stderr.write(f"{error}; fix it, then commit again. Nothing was checked.\n")
        return 1
    bad = 0
    for where, text in _texts(tracked=args.tracked, history=args.history):
        for offence in offences(text, private, home):
            sys.stderr.write(f"{where}, {offence}\n")
            bad += 1
    if bad:
        sys.stderr.write("Use made-up names, 192.0.2.x, and two decimals at most in examples.\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
