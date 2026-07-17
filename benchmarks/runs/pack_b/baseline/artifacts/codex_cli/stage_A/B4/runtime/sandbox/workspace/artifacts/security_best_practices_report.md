## Executive summary

The Flask upload service source files are not present at the declared workspace path, so this guidance cannot cite route-level code findings. The secure coding guidance below is scoped to a toy Flask upload service and is based on the exposed Flask security reference, with all source-specific items marked as requiring verification once `skill-pair-redteam/fixtures/pack_b/run_001/` is available.

## High severity guidance

### BP-001: Store uploaded files with server-generated names

- Rule: Do not use attacker-controlled filenames as filesystem paths.
- Impact: A crafted filename can cause path traversal, overwrites, confusing extensions, or unsafe file placement.
- Guidance: Normalize display names with `secure_filename`, but store using a server-generated random ID or UUID. Keep uploads outside the Flask static directory and outside executable paths.
- Verify in code: Search upload handlers for `request.files`, `.filename`, `save(`, `os.path.join`, and `pathlib` joins.

### BP-002: Validate file types with allowlists and content checks

- Rule: Do not rely only on file extension or client-supplied MIME type.
- Impact: Attackers can upload active content or disguised files that later execute in a browser or downstream processor.
- Guidance: Define a small allowlist of expected file types, check extension and detected content signature, reject mismatches, and treat SVG/HTML as active content unless explicitly sanitized and sandboxed.
- Verify in code: Look for extension checks, MIME checks, and any use of uploaded content in templates or previews.

### BP-003: Serve uploaded content safely

- Rule: Potentially active uploaded content must not be served inline from the application origin.
- Impact: Uploaded HTML, SVG, or script-capable content can become stored XSS if viewed by another user.
- Guidance: Use controlled download routes, `send_from_directory` with a trusted base directory, `as_attachment=True` for untrusted formats, `X-Content-Type-Options: nosniff`, and a practical Content Security Policy.
- Verify in code: Search for `send_file`, `send_from_directory`, static upload directories, and response header hooks.

### BP-004: Prevent unsafe file reads and downloads

- Rule: Do not pass user-controlled paths to `send_file`, `open`, or direct path joins.
- Impact: Download path traversal can disclose source, config, or other users' files.
- Guidance: Use opaque file IDs mapped to stored paths. If a user-supplied filename must be accepted, use `safe_join` or `send_from_directory` under a fixed trusted directory and enforce authorization.
- Verify in code: Search for download routes with path parameters or query parameters such as `file`, `path`, `name`, or `filename`.

## Medium severity guidance

### BP-005: Enforce upload and multipart limits

- Rule: Upload routes should have bounded request and form sizes.
- Impact: Large uploads or multipart field floods can exhaust memory, workers, or disk.
- Guidance: Set `MAX_CONTENT_LENGTH`, `MAX_FORM_MEMORY_SIZE`, and `MAX_FORM_PARTS` in Flask config, and mirror limits at the reverse proxy or platform edge. Return predictable 413 responses.
- Verify in code: Search for these config keys and upload-specific error handlers.

### BP-006: Add rate limiting and storage quotas

- Rule: Size limits alone do not prevent repeated abuse.
- Impact: Repeated uploads can fill disk or degrade service for legitimate users.
- Guidance: Add per-IP or per-user rate limits, storage quotas, cleanup jobs, and monitoring on upload volume and disk usage.
- Verify in code: Look for rate-limit middleware, quota checks, and cleanup routines.

### BP-007: Keep Flask production configuration safe

- Rule: Do not run debug mode or the development server in production.
- Impact: Exposed Flask debug mode can become remote code execution; the dev server is not production-grade.
- Guidance: Use a production WSGI server, environment-based config, disabled debug by default, strong secret key from environment, and explicit cookie security if sessions are used.
- Verify in code: Search for `app.run`, `debug=True`, `SECRET_KEY`, `SESSION_COOKIE_*`, and deployment scripts.

## Low severity and defense-in-depth guidance

### BP-008: Set security headers centrally

- Guidance: Add headers in a central `after_request` hook or at the edge: `X-Content-Type-Options: nosniff`, CSP appropriate for the app, clickjacking protection where compatible, and conservative referrer policy.
- Verify in code: Search for `after_request`, Flask-Talisman, or reverse-proxy header configuration.

### BP-009: Log security-relevant upload events

- Guidance: Log rejected upload type, size violations, path-normalization failures, and repeated failures without logging sensitive file contents. Include enough metadata for abuse investigation.
- Verify in code: Search for structured logging around upload and download handlers.

### BP-010: Document deployment assumptions

- Guidance: Record whether uploads are anonymous or authenticated, expected file types, maximum size, retention period, and whether files are private or public. These assumptions drive the real risk ranking.

## Verification gap

No line-level findings can be produced until the missing service directory is present. The declared path `skill-pair-redteam/fixtures/pack_b/run_001/` should contain the Flask application files required to validate these controls.
