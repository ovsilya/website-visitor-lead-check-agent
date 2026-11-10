#!/usr/bin/env bash
# Let someone open the deployed app (Google sign-in through IAP).
# Usage: ./grant-tester.sh person@example.com [more emails...]
# Remove with: ./grant-tester.sh --remove person@example.com
set -euo pipefail
cd "$(dirname "$0")"
export CLOUDSDK_CONFIG="$PWD/.gcloud"   # this project's sign-in only

PROJECT=${PROJECT:-your-gcp-project-id}
ACTION=add-iam-policy-binding
if [[ "${1:-}" == "--remove" ]]; then ACTION=remove-iam-policy-binding; shift; fi

for EMAIL in "$@"; do
  gcloud projects "$ACTION" "$PROJECT" --member="user:$EMAIL" \
    --role=roles/iap.httpsResourceAccessor --condition=None --format=none
  echo "$ACTION: $EMAIL"
done
