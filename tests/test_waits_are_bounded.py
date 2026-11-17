"""A test that waits on another process fails when its own time is up, and never hangs.

No limit is put on a test or a run from outside. Each wait inside a test carries its own bound,
so a child that never answers fails that one test instead of holding a mutation run for hours.
"""

import subprocess
import sys
import time

import pytest
from waits import line_within


def test_a_child_that_never_answers_fails_the_test_instead_of_hanging():
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE, text=True
    ) as child:
        started = time.monotonic()
        try:
            with pytest.raises(pytest.fail.Exception, match="no line within 1 s"):
                line_within(child.stdout, 1)
        finally:
            child.kill()
    assert time.monotonic() - started < 30


def test_a_line_that_comes_in_time_is_returned_whole():
    with subprocess.Popen(
        [sys.executable, "-c", "print('ready', flush=True)"], stdout=subprocess.PIPE, text=True
    ) as child:
        assert line_within(child.stdout, 30) == "ready\n"
