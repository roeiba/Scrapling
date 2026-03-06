#!/usr/bin/env bash
# deploy_cloudrun.sh - Reference script for deploying the Reddit Spider to GCP Cloud Run
#
# Prerequisites:
#   - gcloud CLI authenticated
#   - Docker running
#   - GCP project set
#
# Usage:
#   ./deploy_cloudrun.sh <PROJECT_ID> <REGION> <GCS_OUTPUT_PATH> [SCHEDULE]
#
# Example:
#   ./deploy_cloudrun.sh my-project us-central1 gs://my-bucket/reddit-data/ "0 */6 * * *"

set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <PROJECT_ID> <REGION> <GCS_OUTPUT_PATH> [SCHEDULE]}"
REGION="${2:?Usage: $0 <PROJECT_ID> <REGION> <GCS_OUTPUT_PATH> [SCHEDULE]}"
GCS_OUTPUT_PATH="${3:?Usage: $0 <PROJECT_ID> <REGION> <GCS_OUTPUT_PATH> [SCHEDULE]}"
SCHEDULE="${4:-0 */6 * * *}"  # Default: every 6 hours

SERVICE_NAME="scrapling-reddit-spider"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/scrapling/${SERVICE_NAME}"

echo "=== Building Docker image ==="
docker build -f Dockerfile.cloudrun -t "${IMAGE_NAME}" .

echo "=== Pushing to Artifact Registry ==="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker push "${IMAGE_NAME}"

echo "=== Deploying to Cloud Run ==="
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --platform managed \
  --memory 2Gi \
  --cpu 2 \
  --timeout 600 \
  --max-instances 1 \
  --no-allow-unauthenticated \
  --set-env-vars "GCS_OUTPUT_PATH=${GCS_OUTPUT_PATH}" \
  --quiet

SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --format "value(status.url)" | cat)

echo "=== Cloud Run service deployed at: ${SERVICE_URL} ==="

echo "=== Creating Cloud Scheduler job ==="
# Create a service account for the scheduler to invoke the service
SA_NAME="${SERVICE_NAME}-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create SA if it doesn't exist
gcloud iam service-accounts describe "${SA_EMAIL}" --project "${PROJECT_ID}" 2>/dev/null || \
  gcloud iam service-accounts create "${SA_NAME}" \
    --project "${PROJECT_ID}" \
    --display-name "Reddit Spider Scheduler Invoker"

# Grant invoker role
gcloud run services add-iam-policy-binding "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role "roles/run.invoker" \
  --quiet

# Create or update the scheduler job
PAYLOAD="{\"subreddit_url\": \"https://www.reddit.com/r/AgentsOfAI/new/\", \"gcs_output_path\": \"${GCS_OUTPUT_PATH}\"}"

gcloud scheduler jobs delete "${SERVICE_NAME}-job" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --quiet 2>/dev/null || true

gcloud scheduler jobs create http "${SERVICE_NAME}-job" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --schedule "${SCHEDULE}" \
  --uri "${SERVICE_URL}" \
  --http-method POST \
  --headers "Content-Type=application/json" \
  --message-body "${PAYLOAD}" \
  --oidc-service-account-email "${SA_EMAIL}" \
  --oidc-token-audience "${SERVICE_URL}" \
  --time-zone "UTC" \
  --quiet

echo "=== Done! Scheduler will invoke ${SERVICE_URL} on schedule: ${SCHEDULE} ==="
echo ""
echo "Manual test:"
echo "  TOKEN=\$(gcloud auth print-identity-token)"
echo "  curl -X POST ${SERVICE_URL} -H \"Authorization: Bearer \${TOKEN}\" -H \"Content-Type: application/json\" -d '${PAYLOAD}'"
