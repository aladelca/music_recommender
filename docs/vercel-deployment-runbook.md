# Vercel Deployment Runbook

Vercel hosts the React/Vite application and provides the same-origin `/api` facade for the AWS
backend. CloudFront is not required: Vercel is the frontend edge and API Gateway is the backend
edge.

The configuration is programmatic in `web/vercel.mjs`. It reads one server-side build variable,
`PRODUCT_API_ORIGIN`, before exporting rewrites and security headers.

## Routing Contract

Routes are evaluated in this order:

```text
/api/:path* -> https://<api-id>.execute-api.<region>.amazonaws.com/:path*
/:path*     -> /index.html
```

API responses receive `Cache-Control: private, no-store, max-age=0`. The SPA receives CSP, HSTS,
referrer, content-type, framing, and permissions headers. Spotify embeds are limited to Spotify's
origin by CSP.

The external rewrite is also what makes the AWS callback response set `__Host-` cookies on the
Vercel host. Do not change normal frontend calls from relative `/api/...` to the API Gateway URL.

## Environment Variables

| Name | Scope | Exposure | Value |
| --- | --- | --- | --- |
| `PRODUCT_API_ORIGIN` | Production and Preview | Vercel build/server configuration only | Exact API Gateway HTTPS origin, no path/trailing slash |
| `VITE_OAUTH_ENABLED` | Production | Public build flag | `true` |
| `VITE_OAUTH_ENABLED` | Preview | Public build flag | `false` |

Only `VITE_OAUTH_ENABLED` may use the `VITE_` prefix. Never configure `SUPABASE_DB_URL`, a Spotify
client secret, refresh token, observability key, or AWS credential in Vercel.

## 1. Create Or Link The Project

From the repository root:

```bash
cd web
npx vercel link
```

Create/select the Outside the Loop project and make `web` its root directory. Linking creates the
project without requiring a successful production OAuth deployment. Record the stable production
origin shown under Vercel Domains, normally:

```text
https://<project>.vercel.app
```

Use that exact value for AWS `APP_BASE_URL`. Do not use a branch preview URL for OAuth.

For Git integration, configure:

- Root Directory: `web`
- Framework: Vite (also declared by `vercel.mjs`)
- Build command: `npm run build`
- Output directory: `dist`
- Production branch: `main`

## 2. Configure Spotify Before Login Testing

Register this exact Spotify redirect URI:

```text
https://<project>.vercel.app/api/auth/spotify/callback
```

Scheme, host, path, and lack of trailing slash must match. Add each intended Spotify Development
Mode tester in the Spotify dashboard. That provider list does not replace the application's
deny-by-default internal approval.

The product requests exactly `user-read-private`, `playlist-modify-private`, and
`playlist-modify-public`. `user-read-private` is required by Spotify's current-user profile endpoint
to establish the stable account identity; it is not used for ranking or listening analysis.

## 3. Deploy AWS And Capture The API Origin

Deploy AWS with the stable Vercel origin first. Then read the safe stack output:

```bash
export STACK_NAME=outside-the-loop-beta
export AWS_REGION_VALUE=us-east-1
export PRODUCT_API_ORIGIN="$(aws cloudformation describe-stacks \
  --region "$AWS_REGION_VALUE" --stack-name "$STACK_NAME" \
  --query 'Stacks[0].Outputs[?OutputKey==`ProductApiUrl`].OutputValue|[0]' \
  --output text)"
export PRODUCT_API_ORIGIN="${PRODUCT_API_ORIGIN%/}"
```

This output is an origin, not a secret.

## 4. Set Vercel Variables

Use the dashboard or CLI. With the CLI, enter values through the interactive prompt/stdin rather
than placing privileged values in command history:

```bash
cd web
npx vercel env add PRODUCT_API_ORIGIN production
npx vercel env add PRODUCT_API_ORIGIN preview
npx vercel env add VITE_OAUTH_ENABLED production
npx vercel env add VITE_OAUTH_ENABLED preview
```

Use the API origin captured above for the first two prompts, `true` for production OAuth, and
`false` for preview OAuth. `PRODUCT_API_ORIGIN` must begin with `https://` and contain no username,
password, path, query, fragment, or trailing slash; `vercel.mjs` fails the build otherwise.

## 5. Build And Deploy Production

Run local frontend gates before the deployment:

```bash
cd web
npm ci
npm audit --audit-level=high
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Reject secret markers in the output:

```bash
if grep -ERiq 'SUPABASE_DB_URL|SPOTIFY_APP_CLIENT_SECRET|postgres(ql)?://' dist; then
  exit 1
fi
```

Deploy:

```bash
npx vercel --prod
```

Vercel Git integration may perform the production deployment after CI instead. Do not allow a Git
deployment to bypass the repository CI gates.

## 6. Verify Production

```bash
bash scripts/verify_vercel_deployment.sh https://<project>.vercel.app
```

The verifier checks:

- Root application shell and `/history` deep-link fallback.
- `/api/health` rewrite and `no-store` behavior.
- CSP/security headers.
- `/api/auth/spotify/start` redirect to Spotify.
- No privileged marker in `web/dist`.

Then complete one browser flow at desktop and mobile widths: login, pending/approved state, explicit
seed selection, discovery polling, evidence, review/reorder, named public/private export, history,
logout, and reconnect. Verify the playlist in the same Spotify account used to sign in.

## Cookie Diagnostics

Expected callback cookies are `Secure`, `Path=/`, `SameSite=Lax`; the session cookie is HTTP-only.
If login loops:

1. Confirm the browser used the production Vercel origin, not API Gateway or a preview.
2. Confirm the Spotify redirect URI and AWS `APP_BASE_URL` are byte-for-byte identical origins.
3. Inspect the callback response through browser developer tools for `Set-Cookie`; do not paste
   cookie values into logs or tickets.
4. Verify `/api/auth/me` traverses the Vercel rewrite and returns `401` only when no valid cookie is
   present.
5. Verify mutations include the exact production `Origin` and frontend-provided CSRF header.

## Custom Domain Change

A custom domain changes the security origin and cannot be introduced as a DNS-only edit. In one
maintenance window:

1. Add and verify the Vercel domain.
2. Register `<new-origin>/api/auth/spotify/callback` in Spotify.
3. Redeploy AWS with `APP_BASE_URL=<new-origin>`.
4. Deploy Vercel against the same API origin.
5. Verify OAuth/cookies, then remove the old callback only after active sessions have migrated.

## Rollback

Use Vercel's previous production deployment for frontend-only regressions. If API contracts also
changed, roll AWS and Vercel back to matching commits. Keep the same stable origin and
`PRODUCT_API_ORIGIN`, run `scripts/verify_vercel_deployment.sh`, and complete an authenticated owner
flow. A rollback must not add CloudFront, expose Supabase, or route product requests to the legacy
S3/DynamoDB API.
