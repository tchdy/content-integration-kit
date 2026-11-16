# Runbook

Operating and troubleshooting the Content Integration Kit. Written for whoever supports it after handover.

## 1. What runs where
| Component | Where | Config |
|---|---|---|
| Web app (FastAPI) | Render web service (Docker) | env vars below |
| Database | SQLite at `$DATA_DIR/kit.db` | `DATA_DIR` |
| Identity provider | mocksaml.com by default; the customer's IdP in a real rollout | `IDP_METADATA_URL` or `IDP_METADATA_FILE` |

> Render's free plan has **no persistent disk**: the database resets on every deploy or restart and is re-seeded
> from `samples/legacy_export.xml`. Fine for a demo; for real use, attach a disk or move to Postgres.

### Environment variables
| Name | Purpose | Default |
|---|---|---|
| `BASE_URL` | Public URL. Must exactly match what the IdP posts to, or SAML fails with "received at … instead of …" | `RENDER_EXTERNAL_URL`, then `http://localhost:8000` |
| `SESSION_SECRET` | Signs session cookies. Rotating it signs everyone out | Render generates it |
| `WEBHOOK_SECRET` | Shared HMAC secret with the webhook sender | Render generates it |
| `WEBHOOK_TOLERANCE_SECONDS` | Max webhook age (replay window) | `300` |
| `IDP_METADATA_URL` / `IDP_METADATA_FILE` | IdP metadata; the file takes precedence | mocksaml.com |

## 2. Routine tasks

### Health check
`GET /healthz` → `{"status":"ok"}`. Render uses this to decide whether a deploy is healthy.

### Run a migration
```bash
python scripts/migrate.py export.xml --dry-run --report dry.json   # 1. review first
python scripts/migrate.py export.xml --report run.json              # 2. then for real
```
Check the report: `reconciled` must be `true`. Every entry in `failures` names a `legacy_id` and the schema errors.
Exit codes: `0` = clean, `1` = some records failed (others imported), `2` = counts don't reconcile (**stop and investigate**).
Re-running is safe: unchanged records are skipped.

### Onboard a customer IdP (Okta / Entra ID / ADFS)
1. Give their admin `https://<app>/saml/metadata` (or these two values):
   Entity ID = `<BASE_URL>/saml/metadata`, ACS URL = `<BASE_URL>/saml/acs` (HTTP-POST).
2. Ask for: NameID format = email; attributes needed (e.g. `groups`).
3. Get their IdP metadata URL and set `IDP_METADATA_URL`. Redeploy.
4. Test with one user, then confirm: `/me` shows the expected email and attributes.

### Rotate the webhook secret
Set the new `WEBHOOK_SECRET` here and in the sender **at the same time**. Events signed with the old secret are
rejected with 401 until the sender switches. A sender that retries will recover on its own.

### Send a test webhook
```bash
WEBHOOK_SECRET=<secret> python scripts/send_webhook.py https://<app>/webhooks/inbound samples/article.xml --event-id test-1
```
Run it again with the same `--event-id` → response status `duplicate`.

## 3. Troubleshooting

### SSO login fails
The ACS returns 401 with the reason; the full reason is also in the logs (`SAML login failed: …`).
Decode the response with the **SAML-tracer** browser extension and compare it field by field:

| Reason contains | Meaning | Fix |
|---|---|---|
| `was received at X instead of Y` | Destination mismatch | `BASE_URL` wrong (http vs https, trailing path, custom domain) |
| `audience` | IdP is configured with a different SP Entity ID | Make IdP's Audience / Entity ID = `<BASE_URL>/saml/metadata` |
| `Signature validation failed` / `No Signature found` | Wrong or rotated IdP certificate, or IdP not signing | Re-fetch IdP metadata; check the IdP signs the response or assertion |
| `SubjectConfirmation` / `NotOnOrAfter` | Expired response; often clock skew or the user pressing Back | Check server clocks (NTP); retry login from the start |
| `InResponseTo` | Response doesn't match the login request in this session (cookie lost, or two tabs) | Check the session cookie survives the redirect (`SameSite=Lax`, HTTPS) |
| HTTP 503 `IdP metadata` | IdP metadata unreachable or incomplete | Check `IDP_METADATA_URL` and that the IdP lists an HTTP-Redirect SSO endpoint + signing cert |

### Webhook rejected
| Response | Meaning | Fix |
|---|---|---|
| 401 `signature mismatch` | Secrets differ, or the sender signed a re-serialised body instead of the exact bytes it sent | Align secrets; sign the raw body bytes |
| 401 `possible replay` | Timestamp older than tolerance: sender's clock is wrong, or it re-sends stored requests without re-signing | Fix the clock; re-sign on every retry |
| 422 | The article fails schema validation; the response lists every error | Fix the content and resend. The same event id is fine because failures aren't recorded |
| 200 `duplicate` | Already processed: expected on retries | Nothing to do |

### Migration record failed
Follow the Claude Code Skill `.claude/skills/xslt-transform-debug/SKILL.md` (reproduce → isolate → fix → add test).

### App won't start: `lxml & xmlsec libxml2 library version mismatch`
lxml and xmlsec linked different libxml2 builds. Install both from source against the system library:
`pip install --no-binary lxml,xmlsec -r requirements.txt` (the Dockerfile already does this).

## 4. Known issues
| Date | Symptom | Cause | Fix |
|---|---|---|---|
| 2026-11 | `/xml/transform/*` returned 500 with `XMLSyntaxError: <no detail available>` after the first transform | xmlsec (SAML) sets restrictive global libxslt security settings; afterwards libxml2 refused to open stylesheet files from disk | Load schema/stylesheets from bytes (`_load_trusted`). Regression test runs in a fresh process, since earlier transforms in the same process hide it |
| 2026-11 | Draft articles appeared in the RSS feed | Two XSLT templates matched drafts with equal priority; the processor picked the later one | `priority="1"` on the draft template; regression test `test_feed_transform_skips_drafts` |
