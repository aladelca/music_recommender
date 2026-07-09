# Operational AWS Music Recommender

## Source Request

Create and execute a plan that turns the current Spotify profile/S3 branch into a genuinely operational AWS product, deploy it with the available AWS CLI access, and validate it end to end.

## Goals

- Deploy the existing single-user music recommender API to AWS in `us-east-1` using the repository's SAM infrastructure.
- Keep catalog and extracted profile datasets in the existing private S3 bucket and runtime state in DynamoDB.
- Protect all state-changing and personal-data API routes with a generated API key stored in Secrets Manager.
- Refresh the configured Spotify user's cached profile automatically on a daily schedule and support manual refresh through the existing API.
- Add production-oriented persistence safeguards, access logs, error alarms, and repeatable secret/deployment/smoke-test scripts.
- Prove the live system can sync the Spotify profile, recommend tracks, persist sessions and feedback, and create one private Spotify playlist.

## Non-Goals

- A browser frontend or static S3/CloudFront website.
- Multi-user Spotify OAuth onboarding, tenant isolation, or public self-service accounts.
- A custom domain, Route 53 zone, or ACM certificate.
- Replacing API-key authentication with Cognito or another identity provider.
- Rebuilding the seed catalog or changing recommendation ranking behavior.
- Fully automated GitHub Actions deployment or creation of a long-lived IAM deploy user.

## Assumptions

- The accepted product scope is the secured single-user backend API described in the prior handoff; the user continued after that scope was stated without requesting multi-user or frontend work.
- AWS account `571600852509` and region `us-east-1` are the intended target, based on `aws sts get-caller-identity`, AWS CLI configuration, and the existing bucket name.
- `s3://music-recommender-571600852509-us-east-1/` remains the data bucket. It currently has S3 public access blocked and default AES-256 server-side encryption.
- Catalog run `20260522052343-7123c483` and profile/interaction run `profile-20260709-live-smoke` have already passed the repository's S3 readiness check.
- The ignored local `.env` contains non-empty Spotify client credentials, Spotify refresh token, and OpenAI API key. Secret values must never be printed, committed, or included in test output.
- The existing `X-API-Key` middleware is the authentication boundary for this private single-user deployment. `/health`, `/docs`, `/redoc`, and `/openapi.json` remain public by design.
- A live playlist smoke test may create one private playlist in the configured Spotify account; its identifier may be reported, but credentials and tokens may not.

## Open Questions

- None.

## Current Repo Context

- Branch `feature/spotify-profile-s3-deployment` is clean, pushed, and two commits ahead of `origin/main` at `9c9365a`.
- `src/music_recommender/api/app.py` defines FastAPI API-key middleware and routes for health, profile sync/status, recommendations, feedback, and playlists.
- `src/music_recommender/api/services.py` selects S3 recommender data and DynamoDB-backed profile, session, feedback, and playlist stores when deployed table names are configured.
- `src/music_recommender/api/lambda_handler.py` adapts the FastAPI app to API Gateway with Mangum.
- `infra/template.yaml` defines the HTTP API, Lambda function, four on-demand DynamoDB tables, log retention, scoped S3 access, dynamic Secrets Manager references, and stack outputs.
- `scripts/deploy_api_sam.sh` performs a local SAM build/deploy but currently assumes the runtime secret and SAM CLI already exist.
- `src/music_recommender/demo_readiness_cli.py` validates Spotify credentials/scopes and S3 datasets without exposing records or credentials.
- The live AWS account currently has the data bucket but no `music-recommender-demo` CloudFormation stack and no `music-recommender/demo/runtime` secret. AWS SAM CLI is not installed; Homebrew is available.
- The standard quality gates are Ruff formatting/lint, mypy, and pytest. The latest verified suite passed 105 tests before this plan.
- Beads feature `music-recommender-uqs` tracks this plan and deployment. Existing task `music-recommender-qx1` tracks the earlier deployment smoke gap and should be closed when the live deployment succeeds.

## Backend/API Integration

- Preserve the existing public route contracts and `X-API-Key` header behavior.
- Add a dedicated scheduled Lambda handler that invokes `DemoApiService.sync_profile()` with bounded defaults and fails visibly when Spotify or DynamoDB fails.
- Trigger scheduled profile refresh through EventBridge/SAM on a configurable daily expression. The job writes only the configured user's normalized profile cache to the users table.
- Keep external calls bounded by the existing Spotify/OpenAI HTTP clients and propagate failures so Lambda error metrics and alarms are meaningful.
- Add an API Gateway access log group and Lambda error alarms. Do not log request authorization headers, secret values, OAuth payloads, or full Spotify profile data.
- Add deployment smoke automation that obtains the API key from Secrets Manager in-memory, validates public/protected behavior, exercises live routes, and prints only redacted operational identifiers/counts.

## Data Model And Persistence

- No API payload or DynamoDB key-schema migration is required.
- Enable DynamoDB point-in-time recovery and AWS-owned encryption on users, sessions, feedback, and playlists tables.
- Retain runtime tables on stack deletion or replacement to prevent accidental state loss; document that retained resources require deliberate cleanup.
- The scheduled profile refresh overwrites the single configured user's profile snapshot using the existing profile cache contract.
- Continue using the existing fixed S3 run IDs for catalog and offline profile interaction data. Daily sync refreshes the DynamoDB profile cache without rewriting medallion datasets.
- Secrets Manager secret `music-recommender/demo/runtime` contains exactly the runtime values consumed by the template: `OPENAI_API_KEY`, `RECOMMENDER_API_KEY`, `SPOTIFY_APP_CLIENT_ID`, `SPOTIFY_APP_CLIENT_SECRET`, and `SPOTIFY_USER_REFRESH_TOKEN`.

## Implementation Tasks

1. [ ] Establish the implementation branch and baseline.
   - Files: `plans/operational-aws-product.md`, Beads issue `music-recommender-uqs`
   - Notes: Create `feature/operational-aws-product` from latest `main`, fast-forward it to include `feature/spotify-profile-s3-deployment`, and run focused baseline tests before production changes.

2. [ ] Add a tested scheduled Spotify profile refresh handler.
   - Files: `src/music_recommender/api/scheduled_profile_handler.py`, `tests/test_scheduled_profile_handler.py`
   - Notes: Write failing tests first. Validate EventBridge input, invoke `DemoApiService.sync_profile()` with explicit bounded defaults, return a redacted summary, and let service exceptions fail the invocation. Never log or return tokens/profile payloads.

3. [ ] Harden and extend the SAM infrastructure for continuous operation.
   - Files: `infra/template.yaml`, `tests/test_infra_template.py`
   - Notes: Write failing template assertions first. Add the scheduled Lambda and daily EventBridge schedule, its log group and permissions, API access logging, Lambda error alarms, DynamoDB point-in-time recovery/encryption/retention, schedule and alarm parameters, and useful outputs. Keep IAM scoped to the users table for the scheduler and existing resources for the API.

4. [ ] Add safe, repeatable runtime secret provisioning.
   - Files: `scripts/sync_runtime_secret.sh`, `tests/test_deployment_scripts.py`, `.env.example`
   - Notes: Write tests first for required checks and redaction guarantees. Load required values from the ignored `.env`, preserve an existing API key or generate a strong one, create/update Secrets Manager without printing secret JSON, and support configurable region/secret name.

5. [ ] Make deployment and live smoke validation repeatable.
   - Files: `scripts/deploy_api_sam.sh`, `scripts/smoke_test_deployed_api.sh`, `tests/test_deployment_scripts.py`
   - Notes: Add strict parameter/readiness checks and stack output discovery. The smoke script must test `/health`, a rejected unauthenticated protected call, profile sync/status, recommendation creation, feedback persistence, playlist creation/idempotent replay, and redacted result output. It must not place literal credentials in repository files or command output.

6. [ ] Document the operational runbook and rollback path.
   - Files: `README.md`, `infra/README.md`, `docs/operational-aws-runbook.md`, `plans/operational-aws-product.md`
   - Notes: Document secret sync, SAM installation, deploy/update, outputs, smoke tests, scheduled refresh, logs/alarms, retained tables, estimated AWS resource shape, and safe rollback without exposing credentials.

7. [ ] Run local quality gates and validate the packaged serverless application.
   - Files: all changed implementation and test files
   - Notes: Run focused tests after each TDD cycle, then Ruff format/check, mypy, full pytest, shell syntax checks, `sam validate --lint`, and `sam build`. Resolve all failures before AWS deployment.

8. [ ] Provision and deploy the live AWS stack.
   - Files: AWS Secrets Manager secret and CloudFormation stack created from `infra/template.yaml`
   - Notes: Install SAM CLI with the supported local package manager, validate current Spotify scopes without printing tokens, provision the runtime secret, deploy `music-recommender-demo` with the existing bucket/run IDs, and record only redacted stack outputs and statuses.

9. [ ] Perform live end-to-end and persistence validation.
   - Files: deployed API Gateway, Lambda, EventBridge, DynamoDB, CloudWatch, and one private Spotify playlist
   - Notes: Run the smoke script, verify users/sessions/feedback/playlists table items, directly invoke the scheduled handler once, confirm EventBridge is enabled and alarms/log groups exist, inspect recent Lambda errors, and rerun S3 readiness. Update both Beads issues and this checklist with redacted evidence.

10. [ ] Commit and push the completed operational branch.
    - Files: all tracked changes and Beads export
    - Notes: Review the diff for secrets/unrelated changes, commit, pull/rebase safely, push, and verify the branch is up to date with origin.

## Tests And Scenarios

- Unit tests: scheduled handler accepts a valid EventBridge event, rejects unrelated input, uses bounded sync defaults, returns only counts/timestamps, and propagates sync failure.
- Infrastructure tests: scheduled function/event wiring, least-privilege DynamoDB access, dynamic secret references, access logs, alarms, table PITR/encryption/retention, and outputs.
- Script tests: missing prerequisites/variables fail before AWS mutation; secret values are never echoed; existing secret API key is preserved; smoke script requires stack outputs and API key.
- Integration tests: existing FastAPI tests continue covering API-key authorization, recommendation sessions, profile sync, feedback validation, playlist idempotency, and DynamoDB adapters.
- Live E2E scenarios: health succeeds without auth; protected profile fails without auth; authenticated profile sync/status succeeds; recommendation returns a session and tracks; feedback records against a recommended track; private playlist creation succeeds and replay is idempotent; DynamoDB contains corresponding records.
- Operational scenarios: scheduled Lambda direct invocation updates the profile; EventBridge rule is enabled; Lambda/API access logs are created; alarms are configured; S3 catalog/profile readiness remains true.
- Regression scenarios: local JSON mode still works, route request/response shapes remain compatible, no secret appears in git diff/test output/log excerpts, and S3 data remains private.

## Validation Commands

```bash
uv run pytest tests/test_scheduled_profile_handler.py tests/test_infra_template.py tests/test_deployment_scripts.py
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
uv run pytest
bash -n scripts/sync_runtime_secret.sh
bash -n scripts/deploy_api_sam.sh
bash -n scripts/smoke_test_deployed_api.sh
sam validate --lint --template-file infra/template.yaml
sam build --template-file infra/template.yaml
uv run music-recommender-demo-readiness check-s3-data --bucket music-recommender-571600852509-us-east-1 --catalog-run-id 20260522052343-7123c483 --profile-run-id profile-20260709-live-smoke
STACK_NAME=music-recommender-demo AWS_REGION_VALUE=us-east-1 bash scripts/smoke_test_deployed_api.sh
```

## Risks And Rollback

- Risk: AWS CLI currently authenticates as the account root user.
  Mitigation: Do not persist or print credentials; deploy only the scoped stack resources. Record follow-up guidance to move future deployments to IAM Identity Center or a deployment role.
  Rollback: Revoke/delete root access keys through the AWS account security workflow after a non-root deployment identity is configured.
- Risk: Dynamic Secrets Manager references are resolved during CloudFormation deployment and secret rotation alone does not update Lambda environment variables.
  Mitigation: The secret sync/deploy runbook redeploys after secret updates.
  Rollback: Restore the prior secret version and redeploy the prior stack template.
- Risk: A live smoke test creates a Spotify playlist.
  Mitigation: Create one clearly named private deployment-smoke playlist and validate idempotent replay to avoid duplicates.
  Rollback: Delete the smoke playlist manually in Spotify after validation if it is not wanted.
- Risk: Daily profile synchronization can fail because Spotify revokes a refresh token or changes scopes.
  Mitigation: Propagate failures to Lambda metrics, alarm on errors, and document token reauthorization.
  Rollback: Disable the EventBridge schedule while keeping manual profile sync available.
- Risk: Retained DynamoDB tables survive stack deletion and may incur small ongoing charges.
  Mitigation: Use on-demand billing and document retained resource cleanup.
  Rollback: Export any required records and explicitly delete retained tables after stack removal.
- Risk: The fixed S3 run IDs become stale.
  Mitigation: Keep daily live profile cache refresh separate from offline datasets and document how to deploy a newer catalog/interaction run.
  Rollback: Redeploy with the previously validated run IDs.

## Handoff Notes

- Do not print `.env`, Secrets Manager values, request authorization headers, OAuth responses, or full Spotify profile data.
- Follow strict TDD for each production code/template/script behavior and mark tasks complete only after relevant tests pass.
- Use `music-recommender-uqs` for implementation status. Close `music-recommender-qx1` only after the live API smoke test succeeds.
- The repository has no Beads skill file at the configured project/global paths; follow the `bd prime` workflow directly.
- A non-root AWS deployment identity remains a security follow-up even if this authorized deployment succeeds with the currently configured CLI credentials.
