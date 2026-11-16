# Content Integration Kit

A small, tested reference implementation of the integration work behind a structured-content rollout:

| Capability | What it shows |
|---|---|
| **SAML 2.0 SSO** | SP-initiated login (python3-saml): SP metadata, ACS, signature/audience/destination/expiry checks, open-redirect protection |
| **XML / XSLT** | XSD validation that reports every error, XXE-hardened parsing, XSLT to HTML and to an RSS feed |
| **Migration** | Legacy CMS export → new model via XSLT: dry run, idempotent re-runs, per-record failure isolation, reconciled report |
| **Webhooks** | HMAC-signed, replay-protected, idempotent receiver; outbound delivery with exponential backoff |
| **Delivery docs** | [Acceptance criteria](docs/ACCEPTANCE_CRITERIA.md) mapped to tests, a [runbook](docs/RUNBOOK.md), and a Claude Code [Skill](.claude/skills/xslt-transform-debug/SKILL.md) for repeat debugging |

38 automated tests run in CI, plus a Docker build and smoke test.

## Try it
```bash
docker build -t kit . && docker run -p 8000:8000 kit
open http://localhost:8000
```
Sign in with SSO at `/saml/login` using the free test IdP [mocksaml.com](https://mocksaml.com) (any email/password).

Without Docker (macOS needs `brew install libxmlsec1 pkg-config` first):
```bash
python -m venv .venv && source .venv/bin/activate
pip install --no-binary lxml,xmlsec -r requirements-dev.txt
pytest -q
python scripts/migrate.py samples/legacy_export.xml --dry-run
uvicorn app.main:app --reload
```

## Deploy (Render, free)
1. Push this repo to GitHub.
2. Render → **New → Blueprint** → choose the repo. `render.yaml` creates the service and generates the secrets.
3. Open the URL Render gives you. `/healthz` should return `{"status":"ok"}`.

## API
| Method | Path | |
|---|---|---|
| GET | `/articles`, `/articles/{id}.html` | Stored articles; HTML via XSLT |
| POST | `/xml/validate` | Body: article XML → `{valid, errors[]}` |
| POST | `/xml/transform/html` · `/xml/transform/feed` | Validate, then transform |
| POST | `/webhooks/inbound` | Headers `X-Timestamp`, `X-Signature: sha256=…`, `X-Event-Id` |
| GET | `/saml/metadata` · `/saml/login` · POST `/saml/acs` · GET `/me` | SSO |

Signature = `HMAC_SHA256(secret, "<timestamp>.<raw body>")`. Send one with `scripts/send_webhook.py`.

## Layout
```
app/            FastAPI app: xml_pipeline, webhooks, saml_sp, db, config
schemas/        article.xsd: the target content model
transforms/     XSLT: legacy→article, article→HTML, article→RSS
scripts/        migrate.py, send_webhook.py
samples/        sample article, invalid article, legacy export (one bad record on purpose)
docs/           acceptance criteria, runbook
.claude/skills/ Claude Code Skill for debugging transforms
```

## How it was built
Built as an AI-assisted delivery exercise with Claude Code. Every behaviour in
[the acceptance criteria](docs/ACCEPTANCE_CRITERIA.md) is pinned by a test, so changes can be made with confidence.
