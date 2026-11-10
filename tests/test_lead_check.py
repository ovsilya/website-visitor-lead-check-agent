"""The agreed lead check on a small made-up RB2B export (no real data).

Run:  .venv/bin/python -m pytest tests -q
"""
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lead_agent.lead_check.engine import run_lead_check  # noqa: E402
from lead_agent.lead_check.workbook import write_workbook  # noqa: E402

SITE = "https://www.example.com"
NEWEST = "2026-09-16 10:00:00 +0000"


def row(first="", title="", company="", website="", email="", pages=(), last=NEWEST, first_seen=None,
        city="Seattle", state="WA", revenue="Above $50M", industry="Information Technology", li=""):
    return {
        "LinkedInUrl": li or (f"https://linkedin.com/in/{first.lower()}" if first else ""),
        "FirstName": first, "LastName": "Test" if first else "", "Title": title, "CompanyName": company,
        "AllTimePageViews": "3", "WorkEmail": email, "Website": website, "Industry": industry,
        "EstimatedEmployeeCount": "5001+", "EstimateRevenue": revenue, "City": city, "State": state,
        "Zipcode": "", "LastSeenAt": last, "FirstSeenAt": first_seen or last, "NewProfile": "false",
        "MostRecentReferrer": "", "RecentPageCount": str(len(pages)),
        "RecentPageUrls": json.dumps([SITE + p for p in pages]), "Tags": "[]", "FilterMatches": "[]",
        "ProfileType": "Person" if first else "Company",
    }


ROWS = [
    # Globex: three YESes, top N = 2 keeps the best two
    row("Ana", "Director, ML Data Platform", "Globex", "globex.com", "ana@globex.com",
        ["/contact", "/solutions/ai-data"], first_seen="2026-09-01 10:00:00 +0000"),
    row("Ben", "ML Engineer", "Globex", "globex.com", "ben@globex.com", ["/solutions/ai-data"]),
    row("Cal", "Data Scientist", "Globex", "globex.com", "cal@globex.com", ["/solutions/ai-data"],
        last="2026-09-05 10:00:00 +0000"),
    # Initech "Owner" on a personal webmail address: wrong company match
    row("Dee", "Owner", "Initech", "initech.com", "dee@initechmail.com", ["/contact"]),
    # own staff
    row("Eve", "VP of AI", "ExampleCo", "example.com", "eve@example.com", ["/contact"]),
    # outside the focus regions
    row("Fay", "Head of AI", "Hooli", "hooli.com", "fay@hooli.com", ["/contact"], city="Lucknow", state="UP"),
    # contact-center service pages are not Contact Us
    row("Gus", "VP Engineering", "Hooli", "hooli.com", "gus@hooli.com", ["/solutions/contact-center-outsourcing"]),
    # senior title, home page only (a real case from the pilot): NO
    row("Hal", "Delivery & Enablement - Principal Enterprise Architect", "Vandelay", "vandelay.com", "hal@vandelay.com", ["/"]),
    # Contact Us only outside the visit window: NO
    row("Ivy", "Head of Data", "Cyberdyne", "cyberdyne.com", "ivy@cyberdyne.com", ["/contact"], last="2026-08-20 10:00:00 +0000"),
    # new logo (non-target, above $50M) with a personal email: YES, find work email
    row("Jon", "VP Data & AI", "Big Insurer", "biginsurer.com", "jon@yahoo.com", ["/solutions/ai-data"]),
    # non-target below $50M: NO
    row("Kim", "Head of AI", "Tiny Co", "tiny.co", "kim@tiny.co", ["/contact"], revenue="$1M - $5M"),
    # unclear title, settled by the callback
    row("Lee", "Research Scientist", "Hooli", "hooli.com", "lee@hooli.com", ["/contact"]),
    # company-only visits: Google reads solution pages (Tier 1 note); a university doesn't count
    row(company="Initech", website="initech.com", pages=["/solutions/ai-data/physical-ai-robotics-data-solutions"]),
    row(company="Initech", website="initech.com", pages=["/solutions/ai-data"]),
    row(company="Big University", website="bigu.edu", pages=["/solutions/ai-data"], industry="Education"),
    # a priority existing client (Marketing's list) is Tier 1; ICP label from the title
    row("Mia", "Head of LLM Evaluation", "Soylent", "soylent.com", "mia@soylent.com", ["/solutions/ai-data"]),
    # GenAI-platform pages aren't AI Data interest
    row("Ned", "VP of AI", "Wayfarer", "wayfarer.com", "ned@wayfarer.com", ["/solutions/genai-platform"]),
    # an AI Data competitor from Marketing's list
    row("Oli", "Head of Data", "Rival Labs", "rivallabs.ai", "oli@rivallabs.ai", ["/contact"]),
]


def export(rows) -> bytes:
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode()


def run(**kw):
    data = export(ROWS)
    # the same file twice counts once
    return run_lead_check([("rb2b_a.csv", data), ("rb2b_b.csv", data)], top_n=2, **kw)


def by_name(people):
    return {r["First Name"]: r for _, r in people.iterrows()}


def test_four_checks():
    p = by_name(run()["people"])
    assert p["Ana"]["Result"] == "YES" and p["Ana"]["Points"] == 3 + 2 + 2 + 1 + 1  # contact, service, leads, repeat, recent
    assert p["Ben"]["Result"] == "YES" and p["Cal"]["Result"] == "YES"
    assert "wrong company match" in p["Dee"]["Why"] and p["Dee"]["Result"] == "RULED OUT"
    assert p["Eve"]["Why"] == "own staff"
    assert p["Fay"]["Why"].startswith("outside focus regions (India)")
    assert p["Gus"]["Result"] == "NO" and "no Contact Us or solution page" in p["Gus"]["Why"]
    assert p["Hal"]["Result"] == "NO"
    assert p["Ivy"]["Result"] == "NO" and "in the visit window" in p["Ivy"]["Why"]
    assert p["Jon"]["Result"] == "YES" and p["Jon"]["Account type"] == "new logo"
    assert "find work email" in p["Jon"]["Flags"] and p["Jon"]["Next step"] == "Find work email (Apollo / ZoomInfo), then SDR to qualify (new logo: check ICP fit)"
    assert p["Kim"]["Why"] == "not a Tier 1/2 account"
    assert p["Lee"]["Result"] == "NO" and "unclear title" in p["Lee"]["Why"]


def test_top_n_and_order():
    s = run()["summary"]
    globex = next(a for a in s["tier_1"] if a["account"] == "Globex")
    assert globex["yes_total"] == 3 and len(globex["leads"]) == 2
    assert [lead["rank"] for lead in globex["leads"]] == [1, 2]
    assert globex["leads"][0]["points"] >= globex["leads"][1]["points"]
    # Ben (seen this week, 4 points) outranks Cal (seen 11 days ago, 3 points)
    assert globex["leads"][1]["title"] == "ML Engineer"
    assert "Globex" not in s["quiet_whales"] and "Initech" not in s["quiet_whales"]  # Initech has a note


def test_account_notes():
    s = run()["summary"]
    notes = s["account_notes"]
    assert [n["account"] for n in notes["tier_1"]] == ["Initech"] and notes["tier_1"][0]["visits"] == 2
    assert all(n["account"] != "Big University" for n in notes["tier_2"])


def test_settle_titles_and_privacy(tmp_path):
    asked = []

    def settle(titles):
        asked.extend(titles)
        return {t: "AI/data practitioner" for t in titles}

    r = run(settle_titles=settle)
    assert "Research Scientist" in asked and "Lee" not in json.dumps(asked)
    p = by_name(r["people"])
    assert p["Lee"]["Result"] == "YES" and "title settled by AI" in p["Lee"]["Flags"]
    # the chat summary carries no names or emails
    text = json.dumps(r["summary"])
    assert "Ana" not in text and "@" not in text and "linkedin.com/in" not in text
    write_workbook(r, str(tmp_path / "out.xlsx"))
    assert pd.read_excel(tmp_path / "out.xlsx", sheet_name="Worth acting on", header=1)["First Name"].notna().all()


def test_priority_clients_competitors_and_genai_platform():
    p = by_name(run()["people"])
    assert p["Mia"]["Result"] == "YES" and p["Mia"]["Account tier"] == 1 and p["Mia"]["Account type"] == "priority account"
    assert p["Ned"]["Result"] == "NO" and "no Contact Us or solution page" in p["Ned"]["Why"]
    assert p["Oli"]["Why"] == "competitor"


def test_icp_labels():
    r = run()
    p = by_name(r["people"])
    assert p["Mia"]["ICP"] == "GenAI data"                        # from the title
    assert p["Ana"]["ICP"] == "Physical AI + GenAI data"          # no hint in title or page: Globex's segment
    assert p["Jon"]["ICP"] == "AI Data (general)"                 # new logo, no hint anywhere
    assert p["Hal"]["ICP"] == ""                                  # only YESes are labelled
    initech = r["summary"]["account_notes"]["tier_1"][0]
    assert initech["icp"] == "Physical AI"                         # read the physical-AI robotics page
    assert r["summary"]["counts"]["yes_by_icp"]["GenAI data"] == 1


RULE_OUT_ROWS = [
    # students and job seekers: ruled out even with strong pages
    row("Pia", "PhD Candidate, Machine Learning", "Hooli", "hooli.com", "pia@hooli.com", ["/contact"]),
    row("Quin", "Data Engineer | Open to work", "Hooli", "hooli.com", "quin@hooli.com", ["/contact"]),
    row("Ray", "AI Intern", "Globex", "globex.com", "ray@globex.com", ["/solutions/ai-data"]),
    # own staff by email domain, though RB2B names another company
    row("Sam", "Head of AI", "Acme Corp", "acme.com", "sam@subsidiary-example.com", ["/contact"]),
    # own staff by company name (Partnerly), no email
    row("Tia", "VP Data", "Partnerly", "partnerly.com", "", ["/contact"]),
    # partner: flagged, not ruled out
    row("Uma", "VP of AI", "Partnerco", "partnerco.com", "uma@partnerco.com", ["/solutions/ai-data"]),
    # a strong title at the same company stays a lead (control)
    row("Val", "Head of AI", "Hooli", "hooli.com", "val@hooli.com", ["/contact"]),
]


def test_students_own_staff_and_partners(tmp_path):
    r = run_lead_check([("rb2b.csv", export(RULE_OUT_ROWS))], top_n=3)
    p = by_name(r["people"])
    for n in ("Pia", "Quin", "Ray"):
        assert p[n]["Result"] == "RULED OUT" and "student or job seeker" in p[n]["Why"], n
    assert p["Sam"]["Result"] == "RULED OUT" and "own staff" in p["Sam"]["Why"]
    assert p["Tia"]["Result"] == "RULED OUT" and "own staff" in p["Tia"]["Why"]
    assert p["Uma"]["Result"] != "RULED OUT" and "partner company" in p["Uma"]["Flags"]
    assert p["Val"]["Result"] == "YES"
    # no ruled-out person reaches the leads; each is listed with the reason in the workbook
    yes = set(r["people"].loc[r["people"]["Result"] == "YES", "First Name"])
    assert not yes & {"Pia", "Quin", "Ray", "Sam", "Tia"}
    write_workbook(r, str(tmp_path / "out.xlsx"))
    allw = pd.read_excel(tmp_path / "out.xlsx", sheet_name="Everyone checked", header=1).set_index("First Name")
    assert allw.loc["Sam", "Result"] == "RULED OUT" and allw.loc["Sam", "Why"] == "own staff"
    assert "student or job seeker" in allw.loc["Pia", "Why"]
