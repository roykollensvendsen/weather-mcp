"""Waits on another process that end in a failure of the waiting test, never in a hang."""

import queue
import threading

import pytest


def line_within(stream, seconds):
    """The next line from `stream`; a failure, not a hang, if none comes within `seconds`.

    The read runs on a thread of its own, since a pipe's readline cannot be given a limit.
    A child that never answers is then the test's failure, which kills it as it unwinds.
    """
    got = queue.Queue()
    threading.Thread(target=lambda: got.put(stream.readline()), daemon=True).start()
    try:
        return got.get(timeout=seconds)
    except queue.Empty:
        pytest.fail(f"no line within {seconds} s")
