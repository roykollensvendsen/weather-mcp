#!/usr/bin/env python3
"""Refuse a commit that would publish where the owner lives.

This repository is public. Nothing in it may name the owner's home, their
street or their town. The checks, on every file given (by default the files
staged for commit), or on the whole history:

- no home-network address: a private IPv4 address (examples use 192.0.2.x);
- no street address, such as a Norwegian street name followed by a number;
- no coordinates in Norway more exact than two decimals, as a pair or as
  ``lat = ...``, except the made-up points the tests use;
- not home itself: its name, or its latitude and longitude on one line, read
  from the owner's ``~/.config/weather-mcp/config.toml``;
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
#: tests/fakes.py, and a latitude too exact for MET in tests/test_cache.py. They are in
#: the history, which cannot be rewritten, so they are named here rather than hidden.
MADE_UP = frozenset({"61.00412", "9.00377", "61.013", "9.012", "61.00001"})
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


def private_values(words: pathlib.Path, config: pathlib.Path) -> tuple[set[str], tuple[str, str] | None]:
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
            point = (f"{lat:.2f}", f"{lon:.2f}")
    return out, point


def offences(text: str, private: set[str], home: tuple[str, str] | None = None) -> list[str]:
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
        lat, lon = home
        # RULE: the home point on one line is refused
        found += [
            f"line {number}: home's point"
            for number, line in enumerate(text.splitlines(), 1)
            if lat in line and lon in line
        ]
    return found


def _line(text: str, at: int) -> int:
    return text.count("\n", 0, at) + 1


def _git(*args: str) -> str:
    command = ["git", *args]
    done = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8", check=True)  # noqa: S603
    return done.stdout


def _texts(*, tracked: bool, history: bool) -> list[tuple[str, str]]:
    """Each place to scan, as (what it is, its text)."""
    if history:
        return [("the history", _git("log", "-p", "--all", "--no-color", "--format=commit %H%n%B"))]
    names = _git("ls-files") if tracked else _git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    out = []
    for name in names.splitlines():
        path = ROOT / name
        try:
            out.append((name, path.read_text(encoding="utf-8")))
        except (FileNotFoundError, IsADirectoryError, UnicodeDecodeError):
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    """Scan the staged files, every tracked file, or the history; 1 when anything is found."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--tracked", action="store_true", help="scan every tracked file")
    parser.add_argument("--history", action="store_true", help="scan every commit on every branch")
    parser.add_argument("--words", default=str(WORDS), help=f"the private list (default {WORDS})")
    parser.add_argument("--config", default=str(CONFIG), help=f"where home is set (default {CONFIG})")
    args = parser.parse_args(argv)
    try:
        private, home = private_values(
            pathlib.Path(args.words).expanduser(), pathlib.Path(args.config).expanduser()
        )
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
