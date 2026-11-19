"""The CI workflow's own promises, read from the file the runner reads."""

import pathlib

WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/checks.yml"


def test_only_a_pull_requests_superseded_run_is_cancelled():
    """The owner's rule (19.11): a new push to a pull request stops its old run; main's runs always finish.

    A main run cut short leaves the ratchet's figures unmeasured for that commit.
    """
    text = WORKFLOW.read_text()
    assert "group: ${{ github.workflow }}-${{ github.ref }}" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "cancel-in-progress: true" not in text
