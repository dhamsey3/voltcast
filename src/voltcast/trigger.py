"""Ask GitHub to rebuild the status page now, instead of waiting for its schedule.

EventBridge invokes this when a daily run finishes, whether it succeeded or
not, and the scheduler invokes it once after the 10:15 deadline check. GitHub's
own cron started runs hours late or dropped them (docs/adr/0006), so the page
follows the pipeline instead.

The GitHub token lives in an SSM SecureString parameter that is created by
hand, never by Terraform, so it stays out of the Terraform state and CI. A
failed dispatch (an expired token, say) raises an error, which the
status-trigger-failed alarm turns into an email.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from collections.abc import Callable
from typing import Any

logging.getLogger().setLevel(logging.INFO)
log = logging.getLogger(__name__)

API = "https://api.github.com"


def dispatch(
    token: str, repository: str, workflow: str, *, ref: str = "main", opener: Callable = urllib.request.urlopen
) -> int:
    """Start ``workflow`` on ``ref``. GitHub answers 204; errors raise HTTPError."""
    request = urllib.request.Request(
        f"{API}/repos/{repository}/actions/workflows/{workflow}/dispatches",
        data=json.dumps({"ref": ref}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "voltcast-status-trigger",
        },
    )
    with opener(request, timeout=10) as response:
        return response.status


def handler(event: dict, context: object = None, ssm: Any = None) -> dict:
    if ssm is None:
        import boto3

        ssm = boto3.client("ssm")
    token = ssm.get_parameter(Name=os.environ["TOKEN_PARAMETER"], WithDecryption=True)["Parameter"]["Value"]
    # EventBridge sends the run's final status; the scheduler sends a reason.
    reason = event.get("detail", {}).get("status") or event.get("reason", "manual")
    status = dispatch(token, os.environ["GITHUB_REPOSITORY"], os.environ["WORKFLOW_FILE"])
    log.info("asked GitHub to rebuild the status page (%s): HTTP %s", reason, status)
    return {"dispatched": status == 204, "reason": reason}
