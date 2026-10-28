#!/bin/sh
# deploys to cloud run. the two secrets have to exist first, see the README.
# max-instances=1 because previous_response_id history lives in memory
set -e

gcloud run deploy cv-agent \
  --source . \
  --region "${REGION:-us-central1}" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 1 \
  --memory 512Mi \
  --timeout 300 \
  --set-secrets GEMINI_API_KEY=gemini-api-key:latest,AGENT_API_KEY=agent-api-key:latest \
  --set-env-vars LLM_MODEL=gemini-3.5-flash,LLM_FALLBACK_MODEL=gemini-3.5-flash-lite
