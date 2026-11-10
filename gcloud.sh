#!/usr/bin/env bash
# gcloud for this project only: uses this folder's .gcloud, never ~/.config/gcloud.
#   ./gcloud.sh auth login you@example.com    (once)
#   ./gcloud.sh config list
export CLOUDSDK_CONFIG="$(cd "$(dirname "$0")" && pwd)/.gcloud"
exec gcloud "$@"
