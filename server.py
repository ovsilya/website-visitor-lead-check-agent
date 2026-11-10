"""ADK API server + our chat page (ui/), styled like the proposal.

  /            the Lead Check chat page
  /run ...     ADK API, only the parts the page uses, for the signed-in user (access.py)
  /download/   a workbook, once: it's deleted from memory when downloaded
  /dev-ui/     ADK's developer UI, only locally with ADK_DEV_UI=1

Conversations and workbooks are in memory only, here and locally, and are cleared
after IDLE_TTL without activity.
"""
import asyncio
import contextlib
import os
import time
import urllib.parse
from pathlib import Path

# No prompt or response text in tracing spans.
os.environ.setdefault("ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS", "false")

import uvicorn
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from google.adk.artifacts import InMemoryArtifactService
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.cli.service_registry import get_service_registry
from google.adk.sessions import InMemorySessionService

from access import APP_NAME, ON_CLOUD_RUN, AccessMiddleware

ROOT = Path(__file__).resolve().parent
IDLE_TTL = 30 * 60  # seconds, same as the uploaded files (lead_agent/uploads.py)
DEV_UI = os.environ.get("ADK_DEV_UI", "").strip().lower() in ("1", "true", "yes")
if DEV_UI and ON_CLOUD_RUN:
    raise SystemExit("ADK_DEV_UI is for local runs only; unset it on Cloud Run.")

# Browser origins allowed to call the API besides the server's own address. On Cloud
# Run that's the service URL (the container sees http behind Google's https front end).
ALLOW_ORIGINS = [o for o in os.environ.get("ALLOW_ORIGINS", "").split(",") if o]

# Our own in-memory services, so the sweeper and the download can reach them.
SESSIONS = InMemorySessionService()
ARTIFACTS = InMemoryArtifactService()
get_service_registry().register_session_service("lead-memory", lambda uri, **kw: SESSIONS)
get_service_registry().register_artifact_service("lead-memory", lambda uri, **kw: ARTIFACTS)


async def sweep_idle(idle_ttl: float = IDLE_TTL) -> None:
    """Deletes conversations (and their workbooks) idle for more than idle_ttl seconds."""
    cutoff = time.time() - idle_ttl
    for s in (await SESSIONS.list_sessions(app_name=APP_NAME)).sessions:
        if s.last_update_time < cutoff:
            for name in await ARTIFACTS.list_artifact_keys(app_name=APP_NAME, user_id=s.user_id, session_id=s.id):
                await ARTIFACTS.delete_artifact(app_name=APP_NAME, user_id=s.user_id, filename=name, session_id=s.id)
            await SESSIONS.delete_session(app_name=APP_NAME, user_id=s.user_id, session_id=s.id)


async def _sweep_every_minute() -> None:
    while True:
        await asyncio.sleep(60)
        await sweep_idle()


@contextlib.asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_sweep_every_minute())
    yield
    task.cancel()


app = get_fast_api_app(
    agents_dir=str(ROOT), web=DEV_UI, allow_origins=ALLOW_ORIGINS or None, lifespan=lifespan,
    session_service_uri="lead-memory://", artifact_service_uri="lead-memory://", use_local_storage=False,
)

# ADK redirects "/" to its dev UI; send it to our page instead.
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/app/")


@app.get("/whoami", include_in_schema=False)
async def whoami(request: Request):
    return {"user": request.state.user, "app": APP_NAME, "dev_ui": DEV_UI}


@app.get("/download/{session_id}/{name}", include_in_schema=False)
async def download(request: Request, session_id: str, name: str):
    """The workbook, once. It's deleted from memory as it's handed over."""
    user = request.state.user
    part = await ARTIFACTS.load_artifact(app_name=APP_NAME, user_id=user, session_id=session_id, filename=name)
    if not part or not part.inline_data:
        raise HTTPException(404, "This workbook was already downloaded or has expired. Run the check again.")
    await ARTIFACTS.delete_artifact(app_name=APP_NAME, user_id=user, filename=name, session_id=session_id)
    quoted = urllib.parse.quote(name)
    return Response(part.inline_data.data, media_type=part.inline_data.mime_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"})


app.mount("/app", StaticFiles(directory=ROOT / "ui", html=True), name="ui")
app.add_middleware(AccessMiddleware, dev_ui=DEV_UI)

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", 8000)))
