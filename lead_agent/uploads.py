"""Uploaded RB2B files, held in memory only.

Raw uploads are never written to artifact storage, the session database or disk.
The plugin takes each attached file out of the user's message (the model and the
session only see a placeholder) and keeps its bytes in this process's memory,
per conversation, until the conversation is idle for UPLOAD_TTL or the server
restarts. The scoring tool reads them from here.

It fails closed: only plain text passes through to the model. Anything else in a
message (a file sent by link, e.g. from Gemini Enterprise, or any other kind of
part) is replaced with a note saying it was removed.
"""
from __future__ import annotations

import time
from typing import Optional

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

UPLOAD_TTL = 30 * 60  # seconds
MAX_BYTES = 30 * 1024 * 1024
ALLOWED = (".csv", ".xlsx")

# session id -> {"files": {name: bytes}, "touched": epoch seconds}
_UPLOADS: dict[str, dict] = {}


def _evict_idle() -> None:
    cutoff = time.time() - UPLOAD_TTL
    for sid in [s for s, v in _UPLOADS.items() if v["touched"] < cutoff]:
        del _UPLOADS[sid]


def uploaded_files(session_id: str) -> dict[str, bytes]:
    _evict_idle()
    entry = _UPLOADS.get(session_id)
    if not entry:
        return {}
    entry["touched"] = time.time()
    return entry["files"]


def placeholder(name: str) -> str:
    return f'[Uploaded file: "{name}" · held in memory only]'


def _plain_text(p: types.Part) -> bool:
    return p.text is not None and set(p.model_dump(exclude_none=True)) <= {"text"}


class InMemoryUploadsPlugin(BasePlugin):
    def __init__(self, name: str = "in_memory_uploads"):
        super().__init__(name)

    async def on_user_message_callback(
        self, *, invocation_context: InvocationContext, user_message: types.Content
    ) -> Optional[types.Content]:
        parts = user_message.parts or []
        if all(_plain_text(p) for p in parts):
            return None
        _evict_idle()
        sid = invocation_context.session.id
        entry = _UPLOADS.setdefault(sid, {"files": {}, "touched": time.time()})
        new_parts = []
        for p in parts:
            blob = p.inline_data
            if blob is None:
                new_parts.append(types.Part(text=p.text) if _plain_text(p) else
                                 types.Part(text="[Removed: only files uploaded on the page can be used]"))
                continue
            name = blob.display_name or "upload"
            data = blob.data or b""
            if not name.lower().endswith(ALLOWED):
                new_parts.append(types.Part(text=f'[Upload refused: "{name}" is not a .csv or .xlsx file]'))
            elif len(data) > MAX_BYTES:
                new_parts.append(types.Part(text=f'[Upload refused: "{name}" is larger than 30 MB]'))
            else:
                entry["files"][name] = data
                new_parts.append(types.Part(text=placeholder(name)))
        entry["touched"] = time.time()
        return types.Content(role=user_message.role, parts=new_parts)
