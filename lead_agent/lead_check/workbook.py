"""The lead check's downloadable workbook (the only output with names and emails)."""
from __future__ import annotations

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

PURPLE = "1F3A5F"
FILL = {"YES": "D9F2C6", "NO": "F5F5F5", "RULED OUT": "FBE6E3"}
LEAD_COLS = ["Account tier", "Account", "Account type", "ICP", "Rank in account", "Points", "Why", "Next step", "Flags",
             "First Name", "Last Name", "Title", "Company", "Work Email", "LinkedIn", "City", "State", "Country",
             "Visits", "Last Seen", "Pages"]
ALL_COLS = ["Result", "Why", "Points", "Account tier", "Account", "Account type", "ICP", "Rank in account", "Shown",
            "Next step", "Flags", "Role", "Persona", "Interest", "First Name", "Last Name", "Title", "Company",
            "Work Email", "LinkedIn", "City", "State", "Country", "Revenue", "Employees", "Industry", "Visits",
            "All-Time PV", "First Seen", "Last Seen", "Pages"]
WIDE = {"Why": 60, "Pages": 70, "Next step": 45, "Title": 40, "Company": 28, "Account": 22, "LinkedIn": 36,
        "Work Email": 30, "Flags": 24, "Persona": 30, "ICP": 22}


def _sheet(xw, name: str, df: pd.DataFrame, note: str) -> None:
    df.to_excel(xw, sheet_name=name, index=False, startrow=1)
    ws = xw.sheets[name]
    ws.cell(row=1, column=1, value=note).font = Font(italic=True, color="6B6675")
    for i, col in enumerate(df.columns, 1):
        c = ws.cell(row=2, column=i)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=PURPLE)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(i)].width = WIDE.get(col, 14)
    if "Result" in df.columns:
        rcol = list(df.columns).index("Result") + 1
        for r in range(3, len(df) + 3):
            fill = FILL.get(ws.cell(row=r, column=rcol).value)
            if fill:
                ws.cell(row=r, column=rcol).fill = PatternFill("solid", fgColor=fill)
    ws.freeze_panes = "C3"
    if len(df):
        ws.auto_filter.ref = f"A2:{get_column_letter(len(df.columns))}{len(df) + 2}"


def write_workbook(result: dict, path: str) -> None:
    s, people, notes = result["summary"], result["people"], result["notes"]
    shown = people[people["Shown"] == "Yes"].sort_values(["Account tier", "Account", "Rank in account"])
    f = s["file"]
    readme = pd.DataFrame({"": [
        f"Website-visitor lead check · {', '.join(f['input_files'])}",
        f"{f['rows']:,} rows · {f['people_identified']:,} people identified · {f['company_only_rows']:,} company-only visits · "
        f"visit window {f['visit_window']}",
        f"{s['counts']['yes']} worth acting on ({s['counts']['shown']} shown, top {s['settings']['top_n']} per account) · "
        f"{s['counts']['account_notes']} account notes · {s['counts']['ruled_out']} ruled out",
        "",
        "Worth acting on: the top N leads per account, ranked by points (ties: most recent visit).",
        "Account notes: Tier 1/2 accounts reading solution pages with no person identified.",
        "Everyone checked: every identified visitor with the four checks, the result and why.",
        "YES = strong role + Contact Us or a solution page in the visit window + Tier 1/2 account + not ruled out.",
        "Points rank the YESes; they never turn a NO into a YES. Scoring is fixed rules; no AI decides.",
        "ICP: the AI Data ICP a lead fits (Physical AI, GenAI data or both), from the pages read, the title, else the account. A label only.",
        "Lists and weights: lead_agent/lead_check/lists/ (Marketing can change them without a code change).",
    ]})
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        readme.to_excel(xw, sheet_name="Read me", index=False, header=False)
        xw.sheets["Read me"].column_dimensions["A"].width = 120
        _sheet(xw, "Worth acting on", shown[LEAD_COLS], "Top leads per account. Personal details: handle as confidential.")
        _sheet(xw, "Account notes", notes, "No person identified; the account read solution pages.")
        _sheet(xw, "Everyone checked", people[ALL_COLS], "All identified visitors, with the four checks.")
        settings = pd.DataFrame(sorted(s["settings"].items()), columns=["Setting", "Value"])
        _sheet(xw, "Settings used", settings, "Point weights and windows used for this run.")
