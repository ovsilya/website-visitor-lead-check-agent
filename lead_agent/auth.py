"""Google Cloud credentials for this project only.

Locally, the agent signs in through the project's own gcloud folder
(`lead-check-agent/.gcloud`, set by run.sh via CLOUDSDK_CONFIG), not the machine-wide
application-default login. On Cloud Run there is no gcloud folder, so we return
None and the service uses its own service account.
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess

from google.oauth2.credentials import Credentials

TOKEN_LIFETIME = datetime.timedelta(minutes=45)  # gcloud tokens last ~60 min


def _gcloud_token(request=None, scopes=None):
    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True, text=True, check=True, env=os.environ,
    ).stdout.strip()
    # google-auth compares expiry against naive UTC
    expiry = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) + TOKEN_LIFETIME
    return token, expiry


def project_credentials() -> Credentials | None:
    config = os.environ.get("CLOUDSDK_CONFIG")
    if not config or not os.path.isdir(config) or not shutil.which("gcloud"):
        return None
    return Credentials(
        token=None,
        refresh_handler=_gcloud_token,
        quota_project_id=os.environ.get("GOOGLE_CLOUD_PROJECT"),
    )
