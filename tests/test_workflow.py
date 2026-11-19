"""The CI workflow's own promises, read from the file the runner reads."""

import pathlib

WORKFLOW = pathlib.Path(__file__).resolve().parent.parent / ".github/workflows/checks.yml"


def test_only_a_pull_requests_superseded_run_is_cancelled():
    """The owner's rule (19.11): a new push to a pull request stops its old run; every other run finishes.

    A main run cut short leaves the ratchet's figures unmeasured for that commit.
    """
    text = WORKFLOW.read_text()
    # Any other run is its own group: one group per ref keeps only one waiting run, and a
    # commit on main between two others would get none.
    assert (
        "group: ${{ github.workflow }}-"
        "${{ github.event_name == 'pull_request' && github.ref || github.run_id }}"
    ) in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "cancel-in-progress: true" not in text
