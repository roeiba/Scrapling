#!/usr/bin/env bash
# deploy_cloudrun.sh - Deploy the Reddit Spider as a Cloud Run Job
#
# Uses Cloud Run Jobs (not Services) — runs container to completion, no HTTP server.
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

JOB_NAME="scrapling-reddit-spider"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/scrapling/${JOB_NAME}"

echo "=== Building Docker image ==="
docker build -f Dockerfile.cloudrun -t "${IMAGE_NAME}" .

echo "=== Pushing to Artifact Registry ==="
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker push "${IMAGE_NAME}"

echo "=== Deploying Cloud Run Job ==="
gcloud run jobs create "${JOB_NAME}" \
  --image "${IMAGE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --memory 2Gi \
  --cpu 2 \
  --task-timeout 600 \
  --max-retries 1 \
  --args="--subreddit-url=https://www.reddit.com/r/AgentsOfAI/new/,--gcs-output-path=${GCS_OUTPUT_PATH}" \
  --quiet 2>/dev/null || \
gcloud run jobs update "${JOB_NAME}" \
  --image "${IMAGE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --memory 2Gi \
  --cpu 2 \
  --task-timeout 600 \
  --max-retries 1 \
  --args="--subreddit-url=https://www.reddit.com/r/AgentsOfAI/new/,--gcs-output-path=${GCS_OUTPUT_PATH}" \
  --quiet

echo "=== Creating Cloud Scheduler ==="
SA_NAME="${JOB_NAME}-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts describe "${SA_EMAIL}" --project "${PROJECT_ID}" 2>/dev/null || \
  gcloud iam service-accounts create "${SA_NAME}" \
    --project "${PROJECT_ID}" \
    --display-name "Reddit Spider Scheduler Invoker"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:${SA_EMAIL}" \
  --role "roles/run.invoker" \
  --quiet

gcloud scheduler jobs delete "${JOB_NAME}-schedule" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --quiet 2>/dev/null || true

gcloud scheduler jobs create http "${JOB_NAME}-schedule" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --schedule "${SCHEDULE}" \
  --uri "https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method POST \
  --oauth-service-account-email "${SA_EMAIL}" \
  --time-zone "UTC" \
  --quiet

echo "=== Done! ==="
echo "Manual run:  gcloud run jobs execute ${JOB_NAME} --project ${PROJECT_ID} --region ${REGION}"
echo "Schedule:    ${SCHEDULE} (UTC)"
