#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-$(aws configure get region)}"
if [[ -z "${REGION}" ]]; then
  REGION="us-east-1"
fi

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${MUSIC_RECOMMENDER_BUCKET:-music-recommender-${ACCOUNT}-${REGION}}"

if aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  echo "Bucket exists: s3://${BUCKET}"
else
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}"
  else
    aws s3api create-bucket \
      --bucket "${BUCKET}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
  echo "Created bucket: s3://${BUCKET}"
fi

EMPTY_FILE="$(mktemp)"
trap 'rm -f "${EMPTY_FILE}"' EXIT

for prefix in bronze/ silver/ gold/ metadata/; do
  aws s3api put-object \
    --bucket "${BUCKET}" \
    --key "${prefix}.keep" \
    --body "${EMPTY_FILE}" >/dev/null
done

echo "Medallion prefixes ready."
echo "export MUSIC_RECOMMENDER_BUCKET=${BUCKET}"
