"""Tools the chat agent can call. All scoring is fixed rules; no AI involved.

- check_leads: the agreed lead check (four checks, two account tiers, top N per account).
"""
from __future__ import annotations

import asyncio
import datetime
import functools
import os
import sys
import tempfile
import traceback
from pathlib import Path

from google.adk.tools.tool_context import ToolContext
from google.genai import types

from .lead_check.engine import LeadCheckError, run_lead_check
from .lead_check.workbook import write_workbook
from .uploads import uploaded_files

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# RAM-backed scratch space when the OS has one (Linux); Cloud Run's filesystem is in memory.
SCRATCH = "/dev/shm" if os.path.isdir("/dev/shm") else None


def _flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in ("1", "true", "yes")


async def _save_workbook(tool_context: ToolContext, out_name: str, workbook: bytes) -> None:
    # In memory only: deleted when downloaded or after 30 idle minutes (server.py).
    await tool_context.save_artifact(out_name, types.Part.from_bytes(data=workbook, mime_type=XLSX_MIME))


def _safe(tool):
    """Any unexpected failure becomes a plain message for the model and the page.

    The error text itself can quote rows from the file, so it never goes to the model,
    and on Cloud Run only the error type is logged.
    """
    @functools.wraps(tool)
    async def run(*args, **kwargs):
        try:
            return await tool(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            if os.environ.get("K_SERVICE"):
                print(f"{tool.__name__} failed: {type(e).__name__}", file=sys.stderr)
            else:
                traceback.print_exc()
            return {"status": "error", "message": "Something went wrong while checking the file. Make sure"
                    " it's an RB2B export and try again; if it keeps failing, tell the app owner."}
    return run


@_safe
async def check_leads(tool_context: ToolContext, top_n: int = 0) -> dict:
    """Runs the agreed lead check on the uploaded RB2B CSV exports.

    Four checks on every identified visitor (who: role; which: account tier;
    what: Contact Us or a solution page in the visit window; rule out: own staff,
    competitors, wrong company matches, students/job seekers, outside the focus
    regions). YESes are ranked by points and the top N per account are shown.
    Company-only visits from Tier 1/2 accounts reading solution pages become
    account notes. Every .csv uploaded in this chat is used; .xlsx files are ignored.

    Args:
      top_n: Leads shown per account (e.g. 3, 5, 10, 20). 0 uses the default (3).

    Returns:
      Counts; Tier 1 and Tier 2 accounts with their top leads (title, points and
      why, pages, flags, next step; no names unless allowed); account notes;
      reasons people were left out or ruled out; and the workbook for download.
    """
    uploads = uploaded_files(tool_context.session.id)
    csvs = sorted(n for n in uploads if n.lower().endswith(".csv"))
    if not csvs:
        return {
            "status": "error",
            "message": "No RB2B .csv file in memory for this chat. Upload it (again): files"
            " are held in memory only and cleared after 30 idle minutes or a restart.",
        }
    out_name = f"Lead Check {datetime.datetime.now().strftime('%Y-%m-%d %H%M')}.xlsx"
    try:
        result = await asyncio.to_thread(
            run_lead_check, [(n, uploads[n]) for n in csvs], top_n=top_n or None,
            include_names=_flag("SHARE_NAMES_WITH_MODEL"),
        )
    except LeadCheckError as e:
        return {"status": "error", "message": str(e)}
    with tempfile.TemporaryDirectory(dir=SCRATCH) as tmp:
        path = Path(tmp) / out_name
        await asyncio.to_thread(write_workbook, result, str(path))
        workbook = path.read_bytes()
    await _save_workbook(tool_context, out_name, workbook)
    return {**result["summary"], "status": "ok", "workbook_for_download": out_name}

