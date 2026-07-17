# Secure Coding Guidance for Toy Node Token Gateway

## Executive summary
The sandbox contains `bootstrapped_inputs.json` but not the declared service source directory, so this guidance is pattern-based for a Node/Express token gateway rather than a line-specific vulnerability report. Apply these controls before treating the gateway as production-ready.

## High priority guidance

### BP-001: Authenticate and authorize every token operation
Impact: unauthenticated token issuance or exchange can become a direct authorization bypass.

Guidance:
- Require authenticated callers for token issue, exchange, introspection, and revocation routes.
- Enforce server-side allowlists for client ID, scope, audience, issuer, token lifetime, and grant type.
- Never trust requested scopes or audiences solely because they appear in a request body.

### BP-002: Use vetted token libraries with strict validation
Impact: permissive token parsing can accept forged, expired, or wrong-audience tokens.

Guidance:
- Use maintained JWT/OAuth libraries instead of custom crypto or hand-rolled claim parsing.
- Pin accepted algorithms and reject `none`.
- Require and validate issuer, audience, expiry, not-before, subject, and key ID expectations.
- Keep signing secrets in environment or secret manager controls, not source files or logs.

### BP-003: Redact tokens from logs, errors, and metrics
Impact: bearer tokens in logs are usually equivalent to credential disclosure.

Guidance:
- Redact `Authorization`, `Cookie`, `Set-Cookie`, `access_token`, `refresh_token`, `id_token`, `api_key`, and similar fields.
- Return generic client errors for token failures; log structured reason codes without raw token values.
- Add automated log scanning for token-like strings.

## Medium priority guidance

### BP-004: Validate all request input at route boundaries
Guidance:
- Add schema validation for JSON bodies, query parameters, headers, and path params.
- Reject unexpected types, extra fields, oversized strings, unknown scopes, and malformed token formats.
- Normalize inputs before use in redirects, upstream requests, or security decisions.

### BP-005: Limit request size and request rate
Guidance:
- Configure explicit `express.json({ limit: "..." })` and `express.urlencoded({ limit, parameterLimit })` values.
- Apply rate limits to token issue, exchange, introspection, and validation routes.
- Use upstream timeouts and bounded retries for identity-provider calls.

### BP-006: Harden Express production defaults
Guidance:
- Use `helmet()` early in middleware order and disable `x-powered-by`.
- Add custom 404 and error handlers that do not leak stack traces in production.
- Configure CORS narrowly; token endpoints should not be broadly callable from arbitrary browser origins unless explicitly designed for that.
- Configure `trust proxy` only for the actual proxy topology, never blindly for the open internet.

### BP-007: Prevent token leakage through redirects and caching
Guidance:
- Do not place bearer tokens in query strings or redirect URLs.
- If redirects are needed, allow only same-site relative paths or exact trusted hosts.
- Set `Cache-Control: no-store` on token responses.

## Review blockers
- The declared fixture path `skill-pair-redteam/fixtures/pack_b/run_002/` is absent from the sandbox, so no file/line-specific findings can be produced.
- Restore the service files and review entrypoints, route handlers, token validation code, middleware order, dependency manifests, tests, and logging configuration.

## Evidence
- `bootstrapped_inputs.json` declares `skill-pair-redteam/fixtures/pack_b/run_002` as the copied workspace input.
- Workspace inspection found only `bootstrapped_inputs.json` and `artifacts/`.
