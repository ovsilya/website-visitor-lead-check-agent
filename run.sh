#!/usr/bin/env bash
# Start the agent + chat page (http://localhost:8000) with this project's sign-in. ADK_DEV_UI=1 adds /dev-ui/.
set -euo pipefail
cd "$(dirname "$0")"
export CLOUDSDK_CONFIG="$PWD/.gcloud"
if ! gcloud auth print-access-token >/dev/null 2>&1; then
  echo "Not signed in for this project. Run: ./gcloud.sh auth login you@example.com" >&2
  exit 1
fi
exec .venv/bin/python server.py
