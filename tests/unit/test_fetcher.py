"""Checkout of pinned commits, including pull request heads from forks."""

from unittest.mock import MagicMock, patch

import pytest

from aggregation.fetcher import DocsFetcher
from aggregation.models import RepoConfig

REPO_URL = "https://github.com/org/repo"
PINNED_COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _recording_run(commit_present: bool):
    """Stub for subprocess.run that records commands and fakes `git cat-file`."""
    calls = []

    def run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        if cmd[:2] == ["git", "cat-file"]:
            result.returncode = 0 if commit_present else 1
        elif cmd[:2] == ["git", "rev-parse"]:
            result.stdout = f"{PINNED_COMMIT}\n"
        return result

    return run, calls


def test_pinned_commit_outside_any_branch_is_fetched_by_name(tmp_path):
    """A fork's pull request head is in refs/pull/*, which `fetch --all` skips."""
    repo = RepoConfig("source", REPO_URL, "docs", "topic", PINNED_COMMIT)
    run, calls = _recording_run(commit_present=False)

    with patch("aggregation.fetcher.subprocess.run", side_effect=run):
        success, commit = DocsFetcher(tmp_path)._fetch_remote(repo, tmp_path / "output")

    assert success
    assert commit == PINNED_COMMIT
    assert calls.index(["git", "fetch", "origin", PINNED_COMMIT]) < calls.index(
        ["git", "checkout", PINNED_COMMIT]
    )


def test_pinned_commit_already_present_is_not_refetched(tmp_path):
    repo = RepoConfig("source", REPO_URL, "docs", "topic", PINNED_COMMIT)
    run, calls = _recording_run(commit_present=True)

    with patch("aggregation.fetcher.subprocess.run", side_effect=run):
        success, _ = DocsFetcher(tmp_path)._fetch_remote(repo, tmp_path / "output")

    assert success
    assert ["git", "fetch", "origin", PINNED_COMMIT] not in calls


def test_commit_fetch_carries_the_remote_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_COM_TOKEN", "public")
    repo = RepoConfig("source", REPO_URL, "docs", "topic", PINNED_COMMIT)
    calls = []

    def run(cmd, *args, **kwargs):
        calls.append((list(cmd), kwargs))
        result = MagicMock()
        result.returncode = 1 if cmd[:2] == ["git", "cat-file"] else 0
        result.stdout = f"{PINNED_COMMIT}\n"
        return result

    with patch("aggregation.fetcher.subprocess.run", side_effect=run):
        DocsFetcher(tmp_path)._fetch_remote(repo, tmp_path / "output")

    fetch = next(
        kwargs
        for cmd, kwargs in calls
        if cmd == ["git", "fetch", "origin", PINNED_COMMIT]
    )
    assert "GIT_CONFIG_COUNT" in fetch["env"]
    assert "public" not in str(calls)


@pytest.mark.parametrize("update_locks", [False, True])
def test_unpinned_checkout_does_not_probe_for_a_commit(tmp_path, update_locks):
    commit = PINNED_COMMIT if update_locks else None
    repo = RepoConfig("source", REPO_URL, "docs", "main", commit)
    run, calls = _recording_run(commit_present=True)

    with patch("aggregation.fetcher.subprocess.run", side_effect=run):
        success, _ = DocsFetcher(tmp_path, update_locks=update_locks)._fetch_remote(
            repo, tmp_path / "output"
        )

    assert success
    assert not any(cmd[:2] == ["git", "cat-file"] for cmd in calls)
    assert ["git", "checkout", "main"] in calls
