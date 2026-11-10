"""Who is calling, and what they may call.

On Cloud Run every request comes through Google sign-in (IAP). The signed-in email,
read from IAP's signed header, is the ADK user id, so a tester only ever reaches
their own conversations and workbooks. Only the endpoints the chat page needs are
open; the rest of ADK's API (listing or deleting sessions, raw artifacts, evals,
live runs) is closed. Locally, without IAP, everyone is the user "local".
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

import requests
from google.auth import jwt

APP_NAME = "lead_agent"
LOCAL_USER = "local"
ON_CLOUD_RUN = bool(os.environ.get("K_SERVICE"))  # set by Cloud Run on every service
# Optional extra check on the token's audience: /projects/NUMBER/locations/REGION/services/NAME
IAP_AUDIENCE = os.environ.get("IAP_AUDIENCE") or None
IAP_ISSUER = "https://cloud.initech.com/iap"
IAP_CERTS_URL = "https://www.gstatic.com/iap/verify/public_key"
MAX_BODY = 48 * 1024 * 1024  # a 30 MB upload, base64 in JSON

# The page loads only its own scripts and styles, and no images or frames from anywhere.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

_certs: dict = {"keys": None, "fetched": 0.0}


def _iap_certs() -> dict:
    if _certs["keys"] is None or time.time() - _certs["fetched"] > 3600:
        _certs["keys"] = requests.get(IAP_CERTS_URL, timeout=10).json()
        _certs["fetched"] = time.time()
    return _certs["keys"]


def iap_user(token: str | None) -> str | None:
    """The signed-in email from IAP's JWT, or None if it's missing or not valid."""
    if not token:
        return None
    try:
        claims = jwt.decode(token, certs=_iap_certs(), audience=IAP_AUDIENCE)
    except Exception:  # bad signature, expired, wrong audience, certs unreachable
        return None
    email = claims.get("email") if claims.get("iss") == IAP_ISSUER else None
    return email.strip().lower() if email else None


def allowed(method: str, path: str, user: str) -> bool:
    """The chat page's endpoints only, and only for the caller's own user id."""
    if method == "GET" and (path in ("/", "/whoami") or path.startswith(("/app/", "/download/"))):
        return True
    sessions = f"/apps/{APP_NAME}/users/{user}/sessions"
    if method == "POST" and path in (sessions, "/run"):
        return True
    return method == "GET" and re.fullmatch(re.escape(sessions) + r"/[\w-]+", path) is not None


class AccessMiddleware:
    """Sets scope["state"]["user"], closes everything the page doesn't use, adds security headers.

    With dev_ui=True (local only) every endpoint stays open for ADK's developer UI.
    """

    def __init__(self, app, dev_ui: bool = False):
        self.app = app
        self.dev_ui = dev_ui

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket" and not self.dev_ui:
            return await send({"type": "websocket.close", "code": 1008})  # live runs: dev UI only
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        if ON_CLOUD_RUN:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            user = await asyncio.to_thread(iap_user, headers.get("x-goog-iap-jwt-assertion"))
            if not user:
                return await _reply(send, 401, "Sign in through the app link (Google sign-in).")
        else:
            user = LOCAL_USER
        scope.setdefault("state", {})["user"] = user

        if not self.dev_ui:
            method, path = scope["method"], scope["path"]
            if not allowed(method, path, user):
                return await _reply(send, 404, "Not found.")
            if path == "/run":
                body = await _read_body(receive)
                if body is None:
                    return await _reply(send, 413, "The upload is too large.")
                try:
                    req = json.loads(body)
                except ValueError:
                    return await _reply(send, 400, "Bad request.")
                if req.get("appName") != APP_NAME or req.get("userId") != user:
                    return await _reply(send, 403, "Not your conversation.")
                receive = _replay(body, receive)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                h = list(message.get("headers", []))
                h += [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                      (b"cache-control", b"no-store")]
                if not self.dev_ui:
                    h += [(b"content-security-policy", CSP.encode()), (b"x-frame-options", b"DENY")]
                message = {**message, "headers": h}
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def _read_body(receive) -> bytes | None:
    chunks, size = [], 0
    while True:
        message = await receive()
        chunk = message.get("body", b"")
        size += len(chunk)
        if size > MAX_BODY:
            return None
        chunks.append(chunk)
        if not message.get("more_body"):
            return b"".join(chunks)


def _replay(body: bytes, receive):
    """Hands the app the body we already read, then the real stream (e.g. a disconnect)."""
    sent = False

    async def replay():
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replay


async def _reply(send, status: int, message: str) -> None:
    body = json.dumps({"detail": message}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
