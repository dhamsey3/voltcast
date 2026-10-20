import io
import json
import urllib.error

import pytest

from voltcast import trigger


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSSM:
    def __init__(self):
        self.asked = []

    def get_parameter(self, Name, WithDecryption):
        self.asked.append((Name, WithDecryption))
        return {"Parameter": {"Value": "test-token"}}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TOKEN_PARAMETER", "/voltcast/github-dispatch-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "dhamsey3/voltcast")
    monkeypatch.setenv("WORKFLOW_FILE", "status.yml")


def test_dispatch_asks_github_to_run_the_workflow_on_main():
    sent = []

    def opener(request, timeout):
        sent.append(request)
        return FakeResponse(204)

    assert trigger.dispatch("test-token", "dhamsey3/voltcast", "status.yml", opener=opener) == 204
    request = sent[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://api.github.com/repos/dhamsey3/voltcast/actions/workflows/status.yml/dispatches"
    assert json.loads(request.data) == {"ref": "main"}
    assert request.get_header("Authorization") == "Bearer test-token"


def test_handler_reads_the_token_and_reports_why(env, monkeypatch):
    calls = []
    monkeypatch.setattr(trigger, "dispatch", lambda token, repo, workflow: calls.append((token, repo, workflow)) or 204)
    ssm = FakeSSM()
    event = {"source": "aws.states", "detail": {"status": "SUCCEEDED"}}
    assert trigger.handler(event, ssm=ssm) == {"dispatched": True, "reason": "SUCCEEDED"}
    assert ssm.asked == [("/voltcast/github-dispatch-token", True)]
    assert calls == [("test-token", "dhamsey3/voltcast", "status.yml")]
    assert trigger.handler({"reason": "deadline"}, ssm=ssm)["reason"] == "deadline"


def test_a_rejected_token_fails_loudly(env):
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Bad credentials", {}, io.BytesIO(b"{}"))

    with pytest.raises(urllib.error.HTTPError):
        trigger.dispatch("expired", "dhamsey3/voltcast", "status.yml", opener=opener)
