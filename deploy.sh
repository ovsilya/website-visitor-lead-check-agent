#!/usr/bin/env bash
# Deploy the agent + chat page to Cloud Run.
# Private: no public access. Google sign-in (IAP) in front; testers are added
# with ./grant-tester.sh <email>. See README "Deploy".
set -euo pipefail
cd "$(dirname "$0")"
export CLOUDSDK_CONFIG="$PWD/.gcloud"   # this project's sign-in only

PROJECT=${PROJECT:-your-gcp-project-id}
REGION=${REGION:-us-central1}
SERVICE=lead-check-agent
NUMBER=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
URL="https://$SERVICE-$NUMBER.$REGION.run.app"
# The app checks IAP's signed token was issued for this service (access.py).
IAP_AUDIENCE=${IAP_AUDIENCE-/projects/$NUMBER/locations/$REGION/services/$SERVICE}

gcloud run deploy "$SERVICE" \
  --project="$PROJECT" --region="$REGION" \
  --source=. \
  --service-account="lead-agent-run@$PROJECT.iam.gserviceaccount.com" \
  --build-service-account="projects/$PROJECT/serviceAccounts/lead-agent-build@$PROJECT.iam.gserviceaccount.com" \
  --no-allow-unauthenticated \
  --set-env-vars="^@^GOOGLE_GENAI_USE_VERTEXAI=TRUE@GOOGLE_CLOUD_PROJECT=$PROJECT@GOOGLE_CLOUD_LOCATION=global@MODEL=gemini-3.5-flash@SHARE_NAMES_WITH_MODEL=false@ALLOW_ORIGINS=$URL@IAP_AUDIENCE=$IAP_AUDIENCE" \
  --memory=2Gi --cpu=2 --timeout=900 \
  --min-instances=0 --max-instances=1 \
  "$@"

# Google sign-in (IAP) in front of the service. This gcloud has no --iap flag,
# so set it through the Cloud Run API (needs run.services.update).
TOKEN=$(gcloud auth print-access-token)
curl -sf -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/services/$SERVICE?updateMask=iapEnabled" \
  -d '{"iapEnabled": true}' > /dev/null
echo "Deployed: $URL (Google sign-in required)"
