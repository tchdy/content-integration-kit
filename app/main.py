"""HTTP API for the Content Integration Kit."""

from __future__ import annotations

import json
import logging
from html import escape

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from . import saml_sp, webhooks, xml_pipeline
from .config import Settings, get_settings
from .db import connect

log = logging.getLogger("kit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

_boot = get_settings()
app = FastAPI(title="Content Integration Kit", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=_boot.session_secret,
    https_only=_boot.base_url.startswith("https"),
    same_site="lax",  # lax still sends the cookie on the top-level redirect back from the IdP
)


# ---------------------------------------------------------------- home / health

@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> str:
    user = request.session.get("user")
    who = f"Signed in as <b>{escape(user['name_id'])}</b> · <a href='/logout'>log out</a>" if user else "<a href='/saml/login'>Sign in with SSO</a>"
    return f"""<!doctype html><meta charset=utf-8><title>Content Integration Kit</title>
<style>body{{font-family:system-ui,sans-serif;max-width:44rem;margin:2rem auto;padding:0 1rem;line-height:1.6}}code{{background:#f3f3f3;padding:1px 4px}}</style>
<h1>Content Integration Kit</h1><p>{who}</p>
<ul>
<li><a href="/articles">GET /articles</a> - migrated / received articles</li>
<li><code>POST /xml/validate</code> - validate article XML against the schema</li>
<li><code>POST /xml/transform/{{html|feed}}</code> - XSLT transforms</li>
<li><code>POST /webhooks/inbound</code> - HMAC-signed, idempotent webhook receiver</li>
<li><a href="/saml/metadata">GET /saml/metadata</a> - SP metadata for the IdP admin</li>
<li><a href="/docs">/docs</a> - OpenAPI</li>
</ul>"""


@app.exception_handler(saml_sp.IdPConfigError)
def idp_config_error(request: Request, exc: saml_sp.IdPConfigError) -> JSONResponse:
    log.error("SAML IdP configuration problem: %s", exc)
    return JSONResponse({"error": "SSO is not configured correctly", "detail": str(exc)}, status_code=503)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------- XML / XSLT

async def _body_doc(request: Request):
    body = await request.body()
    try:
        return xml_pipeline.parse(body)
    except xml_pipeline.XMLInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/xml/validate")
async def xml_validate(request: Request) -> JSONResponse:
    doc = await _body_doc(request)
    result = xml_pipeline.validate(doc)
    return JSONResponse({"valid": result.valid, "errors": result.errors}, status_code=200 if result.valid else 422)


@app.post("/xml/transform/{target}")
async def xml_transform(target: str, request: Request, cfg: Settings = Depends(get_settings)) -> Response:
    doc = await _body_doc(request)
    result = xml_pipeline.validate(doc)
    if not result.valid:  # never transform unvalidated input: garbage in, garbage out downstream
        return JSONResponse({"valid": False, "errors": result.errors}, status_code=422)
    if target == "html":
        return HTMLResponse(xml_pipeline.to_html(doc))
    if target == "feed":
        item = xml_pipeline.to_feed_item(doc, cfg.base_url)
        if item is None:
            return Response(status_code=204)  # drafts are not syndicated
        return Response(item, media_type="application/xml")
    raise HTTPException(status_code=404, detail="target must be 'html' or 'feed'")


# ---------------------------------------------------------------- articles

@app.get("/articles")
def list_articles(cfg: Settings = Depends(get_settings)) -> list[dict]:
    with connect(cfg.db_path) as conn:
        rows = conn.execute("SELECT id, legacy_id, title, status, updated_at FROM articles ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.get("/articles/{article_id}.html", response_class=HTMLResponse)
def article_html(article_id: str, cfg: Settings = Depends(get_settings)) -> str:
    with connect(cfg.db_path) as conn:
        row = conn.execute("SELECT xml FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="article not found")
    return xml_pipeline.to_html(xml_pipeline.parse(row["xml"]))


# ---------------------------------------------------------------- webhooks

@app.post("/webhooks/inbound")
async def webhook_inbound(request: Request, cfg: Settings = Depends(get_settings)) -> JSONResponse:
    body = await request.body()  # raw bytes: the signature is over exactly what was sent
    try:
        webhooks.verify(
            cfg.webhook_secret,
            request.headers.get(webhooks.TIMESTAMP_HEADER),
            request.headers.get(webhooks.SIGNATURE_HEADER),
            body,
            cfg.webhook_tolerance_seconds,
        )
    except webhooks.SignatureError as exc:
        log.warning("webhook rejected: %s", exc)
        return JSONResponse({"error": "invalid signature", "reason": str(exc)}, status_code=401)

    try:
        event = json.loads(body)
        event_id = request.headers.get(webhooks.EVENT_ID_HEADER) or event["id"]
        event_type = event["type"]
    except (ValueError, KeyError):
        return JSONResponse({"error": "body must be JSON with 'id' and 'type'"}, status_code=400)

    # Validate before recording, so a bad payload can be fixed and re-sent with the same id.
    article = None
    if event_type == "content.published":
        try:
            article = xml_pipeline.parse(event.get("data", {}).get("xml", ""))
        except xml_pipeline.XMLInputError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        result = xml_pipeline.validate(article)
        if not result.valid:
            return JSONResponse({"error": "article failed schema validation", "errors": result.errors}, status_code=422)

    with connect(cfg.db_path) as conn:
        if not webhooks.record_event_once(conn, event_id, event_type, body.decode()):
            log.info("duplicate webhook %s ignored", event_id)
            return JSONResponse({"status": "duplicate", "event_id": event_id})  # 200 so the sender stops retrying
        if article is not None:
            root = article.getroot()
            conn.execute(
                """INSERT INTO articles (id, legacy_id, title, status, xml, checksum)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, status=excluded.status,
                     xml=excluded.xml, checksum=excluded.checksum, updated_at=datetime('now')""",
                (root.get("id"), root.get("legacy-id"), root.findtext("title"), root.get("status"),
                 xml_pipeline.canonical_bytes(article).decode(), xml_pipeline.checksum(article)),
            )
    log.info("webhook %s (%s) processed", event_id, event_type)
    return JSONResponse({"status": "processed", "event_id": event_id})


# ---------------------------------------------------------------- SAML SSO

@app.get("/saml/metadata")
def saml_metadata(cfg: Settings = Depends(get_settings)) -> Response:
    return Response(saml_sp.sp_metadata(cfg), media_type="application/xml")


@app.get("/saml/login")
def saml_login(request: Request, next: str = "/me", cfg: Settings = Depends(get_settings)) -> RedirectResponse:
    auth = saml_sp.auth_for(cfg, "/saml/login")
    url = auth.login(return_to=saml_sp.safe_relay_state(next))
    request.session["saml_request_id"] = auth.get_last_request_id()  # checked against InResponseTo
    return RedirectResponse(url, status_code=302)


@app.post("/saml/acs")
async def saml_acs(request: Request, cfg: Settings = Depends(get_settings)) -> Response:
    form = await request.form()
    auth = saml_sp.auth_for(cfg, "/saml/acs", post=dict(form))
    request_id = request.session.pop("saml_request_id", None)
    auth.process_response(request_id=request_id)
    errors = auth.get_errors()
    if errors or not auth.is_authenticated():
        # Log the precise reason for support; show the user a generic message.
        log.warning("SAML login failed: errors=%s reason=%s", errors, auth.get_last_error_reason())
        return PlainTextResponse(f"SSO login failed: {', '.join(errors) or 'not authenticated'}\n"
                                 f"Reason: {auth.get_last_error_reason()}", status_code=401)
    request.session["user"] = {
        "name_id": auth.get_nameid(),
        "attributes": auth.get_attributes(),
        "session_index": auth.get_session_index(),
    }
    return RedirectResponse(saml_sp.safe_relay_state(form.get("RelayState")), status_code=303)


@app.get("/me")
def me(request: Request) -> Response:
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/saml/login", status_code=302)
    return JSONResponse(user)


@app.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=302)
