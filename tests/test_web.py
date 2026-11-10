"""The web layer: who the caller is, what they may call, uploads and links (no real data, no model calls).

Run:  .venv/bin/python -m pytest tests -q
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from google.auth import crypt, jwt
from google.genai import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import access  # noqa: E402
from lead_agent.links import page_link  # noqa: E402
from lead_agent.uploads import InMemoryUploadsPlugin, uploaded_files  # noqa: E402


# ---------------- links ----------------
def test_page_links_drop_query_fragment_and_other_schemes():
    assert page_link("https://www.example.com/contact?email=a@b.com&utm=x#top") == "https://www.example.com/contact"
    assert page_link("https://user:pw@www.example.com/x") == "https://www.example.com/x"
    assert page_link("javascript:alert(1)") == ""
    assert page_link("not a url") == ""


# ---------------- uploads ----------------
def _plugin_run(parts):
    ctx = SimpleNamespace(session=SimpleNamespace(id=f"s-{time.time_ns()}"))
    out = asyncio.run(InMemoryUploadsPlugin().on_user_message_callback(
        invocation_context=ctx, user_message=types.Content(role="user", parts=parts)))
    return ctx.session.id, out


def test_plugin_leaves_plain_text_alone():
    _, out = _plugin_run([types.Part(text="hello")])
    assert out is None


def test_plugin_keeps_csv_in_memory_and_sends_only_a_placeholder():
    sid, out = _plugin_run([types.Part(text="check this"),
                            types.Part(inline_data=types.Blob(data=b"a,b\n1,2", mime_type="text/csv", display_name="w.csv"))])
    assert uploaded_files(sid) == {"w.csv": b"a,b\n1,2"}
    assert [p.text for p in out.parts] == ["check this", '[Uploaded file: "w.csv" · held in memory only]']
    assert all(p.inline_data is None for p in out.parts)


def test_plugin_fails_closed_on_files_sent_by_link_and_other_parts():
    sid, out = _plugin_run([types.Part(file_data=types.FileData(file_uri="gs://bucket/rb2b.csv", mime_type="text/csv")),
                            types.Part(text="x", thought=True)])
    assert uploaded_files(sid) == {}
    assert [p.text for p in out.parts] == ["[Removed: only files uploaded on the page can be used]"] * 2
    assert all(set(p.model_dump(exclude_none=True)) == {"text"} for p in out.parts)


# ---------------- who is calling ----------------
@pytest.fixture
def iap_key(monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(access, "_certs", {"keys": {"k1": pub.decode()}, "fetched": time.time()})
    signer = crypt.ES256Signer.from_string(pem, key_id="k1")

    def token(**claims):
        now = int(time.time())
        body = {"iss": access.IAP_ISSUER, "aud": "/projects/1/locations/r/services/s", "email": "Tester@example.com",
                "iat": now, "exp": now + 600, **claims}
        return jwt.encode(signer, body).decode()
    return token


def test_iap_user_reads_the_signed_email(iap_key):
    assert access.iap_user(iap_key()) == "tester@example.com"


def test_iap_user_rejects_bad_tokens(iap_key, monkeypatch):
    assert access.iap_user(None) is None
    assert access.iap_user("not-a-jwt") is None
    assert access.iap_user(iap_key(iss="https://evil.example")) is None
    assert access.iap_user(iap_key(exp=int(time.time()) - 60)) is None
    monkeypatch.setattr(access, "IAP_AUDIENCE", "/projects/2/locations/r/services/s")
    assert access.iap_user(iap_key()) is None


def test_only_the_pages_endpoints_for_your_own_user():
    me = "a@example.com"
    ok = [("GET", "/"), ("GET", "/whoami"), ("GET", "/app/app.js"), ("GET", "/download/s1/w.xlsx"), ("POST", "/run"),
          ("POST", f"/apps/lead_agent/users/{me}/sessions"), ("GET", f"/apps/lead_agent/users/{me}/sessions/abc-123")]
    closed = [("GET", f"/apps/lead_agent/users/{me}/sessions"),               # list all conversations
              ("GET", "/apps/lead_agent/users/b@example.com/sessions/abc"),  # someone else's
              ("DELETE", f"/apps/lead_agent/users/{me}/sessions/abc"),
              ("GET", f"/apps/lead_agent/users/{me}/sessions/abc/artifacts/w.xlsx"),
              ("POST", "/run_sse"), ("GET", "/list-apps"), ("GET", "/dev-ui/"), ("GET", "/docs"), ("GET", "/openapi.json")]
    assert all(access.allowed(m, p, me) for m, p in ok)
    assert not any(access.allowed(m, p, me) for m, p in closed)


# ---------------- the server, end to end (no model calls) ----------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import server
    with TestClient(server.app) as c:
        c.server = server
        yield c


def test_server_closes_adk_endpoints_and_sets_headers(client):
    r = client.get("/whoami")
    assert r.json()["user"] == "local" and r.json()["dev_ui"] is False
    assert "script-src 'self'" in r.headers["content-security-policy"]
    for path in ["/list-apps", "/dev-ui/", "/apps/lead_agent/users/local/sessions", "/docs"]:
        assert client.get(path).status_code == 404, path
    sid = client.post("/apps/lead_agent/users/local/sessions", json={}).json()["id"]
    assert client.get(f"/apps/lead_agent/users/local/sessions/{sid}").status_code == 200
    r = client.post("/run", json={"appName": "lead_agent", "userId": "someone-else", "sessionId": sid,
                                  "newMessage": {"role": "user", "parts": [{"text": "hi"}]}})
    assert r.status_code == 403


def test_workbook_downloads_once(client):
    server = client.server
    sid = client.post("/apps/lead_agent/users/local/sessions", json={}).json()["id"]
    part = types.Part.from_bytes(data=b"xlsx-bytes", mime_type="application/octet-stream")
    client.portal.call(lambda: server.ARTIFACTS.save_artifact(
        app_name="lead_agent", user_id="local", session_id=sid, filename="Lead Check.xlsx", artifact=part))
    r = client.get(f"/download/{sid}/Lead%20Check.xlsx")
    assert r.status_code == 200 and r.content == b"xlsx-bytes"
    assert "attachment" in r.headers["content-disposition"]
    assert client.get(f"/download/{sid}/Lead%20Check.xlsx").status_code == 404


def test_on_cloud_run_the_user_comes_from_iap(client, iap_key, monkeypatch):
    monkeypatch.setattr(access, "ON_CLOUD_RUN", True)
    assert client.get("/whoami").status_code == 401
    h = {"x-goog-iap-jwt-assertion": iap_key()}
    assert client.get("/whoami", headers=h).json()["user"] == "tester@example.com"
    assert client.post("/apps/lead_agent/users/local/sessions", json={}, headers=h).status_code == 404
    sid = client.post("/apps/lead_agent/users/tester@example.com/sessions", json={}, headers=h).json()["id"]
    other = {"x-goog-iap-jwt-assertion": iap_key(email="other@example.com")}
    assert client.get(f"/apps/lead_agent/users/tester@example.com/sessions/{sid}", headers=other).status_code == 404
    assert client.get(f"/download/{sid}/anything.xlsx", headers=other).status_code == 404
    body = {"appName": "lead_agent", "userId": "tester@example.com", "sessionId": sid,
            "newMessage": {"role": "user", "parts": [{"text": "hi"}]}}
    assert client.post("/run", content=json.dumps(body), headers={**other, "content-type": "application/json"}).status_code == 403


def test_idle_conversations_and_workbooks_are_swept(client):
    server = client.server
    sid = client.post("/apps/lead_agent/users/local/sessions", json={}).json()["id"]
    part = types.Part.from_bytes(data=b"x", mime_type="application/octet-stream")
    keys = lambda: client.portal.call(lambda: server.ARTIFACTS.list_artifact_keys(
        app_name="lead_agent", user_id="local", session_id=sid))
    client.portal.call(lambda: server.ARTIFACTS.save_artifact(
        app_name="lead_agent", user_id="local", session_id=sid, filename="w.xlsx", artifact=part))
    client.portal.call(server.sweep_idle)  # 30 minutes: still active
    assert client.get(f"/apps/lead_agent/users/local/sessions/{sid}").status_code == 200 and keys() == ["w.xlsx"]
    client.portal.call(server.sweep_idle, -1)  # everything counts as idle
    assert client.get(f"/apps/lead_agent/users/local/sessions/{sid}").status_code == 404 and keys() == []
