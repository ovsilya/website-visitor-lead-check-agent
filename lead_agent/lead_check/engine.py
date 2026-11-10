"""The agreed lead check (Marketing, 2026-10-07): four checks, two account tiers,
points, top N per account, and account notes. Fixed rules only; no AI decides.

  1. Clean up: read the RB2B exports, drop duplicate files, merge each person's rows.
  2. Four checks on every identified visitor:
       WHO        strong role (leads/buys AI/data, or a practitioner)   titles.py
       WHICH      Tier 1 (whales + priority existing accounts) or Tier 2 (target accounts + new logos)
       WHAT       strong interest: Contact Us or a solution page, within the visit window
       RULE OUT   own staff, competitors, wrong company matches, students/job seekers,
                  outside the focus regions
     YES = strong role + strong interest + Tier 1/2 + not ruled out.
  3. Rank the YESes by points (ties: most recent visit).  4. Top N per account.
  Company-only visits from Tier 1/2 accounts that opened solution pages become account notes.
  Each lead and note is labelled with the AI Data ICP it fits (Physical AI, GenAI data or both);
  the label never changes the result.

The only place AI may come in is `settle_titles`: a callback that settles unclear
job titles (e.g. "Research Scientist") from the title text alone.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from typing import Callable

import pandas as pd

from ..links import page_link
from .lists import Lists, load_lists
from .titles import LEADS, NO_TITLE, PRACTITIONER, UNCLEAR, WEAK, role

# Columns the check reads; anything missing in an export is treated as empty.
COLUMNS = ["LinkedInUrl", "FirstName", "LastName", "Title", "CompanyName", "AllTimePageViews", "WorkEmail",
           "Website", "Industry", "EstimatedEmployeeCount", "EstimateRevenue", "City", "State", "Zipcode",
           "LastSeenAt", "FirstSeenAt", "RecentPageUrls"]
STUDENT = re.compile(r'(?<![a-z])(student|intern|internship|undergraduate|graduate student|phd candidate|'
                     r'job seeker|seeking (new )?opportunit|open to work|looking for (new )?opportunit|'
                     r'aspiring|fresher|unemployed|career break)(?![a-z])', re.I)
URL = re.compile(r'https?://[^\s"\'\],]+')
MAX_LINKS = 4
KIND_ORDER = {"contact": 0, "service": 1, "article": 2}

SettleTitles = Callable[[list[str]], dict[str, str]]


class LeadCheckError(RuntimeError):
    pass


# ---------------- helpers ----------------
def norm_domain(w: str) -> str:
    w = str(w).lower().strip()
    w = re.sub(r'^https?://', '', w)
    w = re.sub(r'^www\.', '', w)
    return w.split('/')[0].split('?')[0].strip()


def _in_domains(d: str, domains: set[str]) -> bool:
    return bool(d) and (d in domains or any(d.endswith('.' + x) for x in domains))


def _name_hit(company: str, names: list[str]) -> bool:
    c = company.lower()
    return any(re.search(r'(?<![a-z0-9])' + re.escape(n) + r'(?![a-z0-9])', c) for n in names)


def match_account(website: str, company: str, L: Lists) -> dict | None:
    """Target-account match, as in the original weekly report: website domain, its aliases and
    subdomains, then the company name."""
    d = norm_domain(website)
    if d:
        if d in L.aliases and L.aliases[d] in L.accounts:
            return L.accounts[L.aliases[d]]
        if d in L.accounts:
            return L.accounts[d]
        for t in L.accounts:
            if d.endswith('.' + t):
                return L.accounts[t]
        for a, t in L.aliases.items():
            if d.endswith('.' + a) and t in L.accounts:
                return L.accounts[t]
    c = re.sub(r'[^a-z0-9 &\-\.]', '', company.lower().strip())
    c = re.sub(r'\s+(inc|inc\.|corp|corporation|llc|ltd|co|co\.|company|group|technologies)$', '', c).strip()
    if c in L.company_names and L.company_names[c] in L.accounts:
        return L.accounts[L.company_names[c]]
    return None


def locate(city: str, state: str, L: Lists) -> str:
    """Country from RB2B's city and state (there is no country column). '' if unknown."""
    c, s = city.strip().lower(), state.strip().upper()
    return L.cities.get((c, s)) or L.cities.get((c, "")) or L.state_codes.get(s, "")


def _paths(cell: str) -> list[str]:
    cell = str(cell).strip()
    if not cell:
        return []
    try:
        v = json.loads(cell)
        urls = v if isinstance(v, list) else [v]
    except ValueError:
        urls = URL.findall(cell)
    return [str(u).strip().strip('"').rstrip('/') for u in urls if str(u).strip()]


def _path(url: str) -> str:
    return (re.sub(r'^https?://[^/]+', '', url).split('?')[0].split('#')[0].rstrip('/') or '/').lower()


def page_kinds(urls, L: Lists) -> dict[str, list[str]]:
    """{kind: [urls]} for contact / service / article pages."""
    out: dict[str, list[str]] = {}
    for u in urls:
        p = _path(u)
        for kind, pat in L.pages:
            if pat.search(p):
                out.setdefault(kind, []).append(u)
                break
    return out


def icp_label(paths: list[str], title: str, segment: str, L: Lists) -> str:
    """Which AI Data ICP a lead or note fits: from the AI Data pages read and the title,
    else from the account's segment. Only a label; it never changes the result."""
    def hits(kinds, texts):
        return {icp for icp, k, pat in L.icp if k in kinds for t in texts if t and pat.search(t)}
    found = hits(("page",), [_path(u) for u in paths]) | hits(("title",), [title])
    found = found or hits(("segment",), [segment.lower()])
    return " + ".join(sorted(found, reverse=True)) if found else "AI Data (general)"


def _sorted_links(urls, L: Lists) -> list[str]:
    kinds = {u: k for k, us in page_kinds(urls, L).items() for u in us}
    return sorted(dict.fromkeys(urls), key=lambda u: KIND_ORDER.get(kinds.get(u), 3))


# ---------------- read ----------------
def read_exports(csv_files: list[tuple[str, bytes]]) -> tuple[pd.DataFrame, list[str]]:
    if not csv_files:
        raise LeadCheckError("No RB2B CSV files were provided.")
    seen, frames, used = set(), [], []
    for name, data in csv_files:
        h = hashlib.md5(data).hexdigest()
        if h in seen:
            continue  # the same export uploaded twice
        seen.add(h)
        df = pd.read_csv(io.BytesIO(data), dtype=str, low_memory=False).fillna('')
        if "RecentPageUrls" not in df.columns or "CompanyName" not in df.columns:
            raise LeadCheckError(f"{name} doesn't look like an RB2B export (no RecentPageUrls / CompanyName column).")
        df["__file"] = name
        frames.append(df)
        used.append(name)
    raw = pd.concat(frames, ignore_index=True).fillna('')
    for c in COLUMNS:
        raw[c] = raw[c].astype(str).str.strip() if c in raw.columns else ''
    raw["__last"] = pd.to_datetime(raw["LastSeenAt"], utc=True, errors="coerce", format="mixed")
    raw["__first"] = pd.to_datetime(raw["FirstSeenAt"], utc=True, errors="coerce", format="mixed")
    return raw, used


# ---------------- the check ----------------
def run_lead_check(csv_files: list[tuple[str, bytes]], lists: Lists | None = None, top_n: int | None = None,
                   settle_titles: SettleTitles | None = None, include_names: bool = False) -> dict:
    """Runs the agreed lead check on RB2B exports.

    Returns {"summary": ..., "people": DataFrame, "notes": DataFrame}. The summary
    has no names, emails or LinkedIn URLs unless include_names is True; the
    DataFrames (for the workbook download) have everything.
    """
    L = lists or load_lists()
    S = L.settings
    top_n = int(top_n or S["top_n"])
    raw, used = read_exports(csv_files)
    newest = raw["__last"].max()
    if pd.isna(newest):
        raise LeadCheckError("No LastSeenAt dates in the file, so the visit window can't be set.")
    window_start = newest - pd.Timedelta(days=int(S["window_days"]))
    recent_start = newest - pd.Timedelta(days=int(S["recent_days"]))

    is_person = raw["FirstName"] != ''
    persons, companies = raw[is_person].copy(), raw[~is_person].copy()

    # 1. one row per person: LinkedIn URL, else name + email (the original report's key)
    li = persons["LinkedInUrl"].str.lower().str.rstrip('/')
    fb = (persons["FirstName"] + '|' + persons["LastName"] + '|' + persons["WorkEmail"]).str.lower()
    persons["__key"] = li.where(li != '', fb)
    agg: dict[str, dict] = {}
    for _, r in persons.sort_values("__last", na_position="first").iterrows():
        a = agg.setdefault(r["__key"], {"rows": 0, "urls": [], "recent_urls": [], "days": set(),
                                        "first": r["__first"], "last": r["__last"], "pv": 0})
        a["rec"] = r  # latest row wins for title, company, location
        a["rows"] += 1
        urls = _paths(r["RecentPageUrls"])
        a["urls"] += urls
        if pd.notna(r["__last"]):
            a["days"].add(r["__last"].date())
            a["last"] = r["__last"] if pd.isna(a["last"]) else max(a["last"], r["__last"])
            if r["__last"] >= window_start:
                a["recent_urls"] += urls
        if pd.notna(r["__first"]):
            a["first"] = r["__first"] if pd.isna(a["first"]) else min(a["first"], r["__first"])
        try:
            a["pv"] = max(a["pv"], int(float(r["AllTimePageViews"] or 0)))
        except ValueError:
            pass

    # unclear titles: settled once per distinct title, by the callback if given
    roles = {k: role(a["rec"]["Title"]) for k, a in agg.items()}
    unclear = sorted({a["rec"]["Title"] for k, a in agg.items() if roles[k][0] == UNCLEAR})
    settled = {}
    if settle_titles and unclear:
        settled = {t: v for t, v in (settle_titles(unclear) or {}).items() if v in (LEADS, PRACTITIONER, WEAK)}

    rows = [_check_person(k, a, roles[k], settled, L, recent_start) for k, a in agg.items()]
    people = pd.DataFrame(rows)
    if people.empty:
        people = pd.DataFrame(columns=["Result", "Points", "Account key", "__last"])

    # 3-4. rank the YESes and keep the top N per account
    yes = people[people["Result"] == "YES"].sort_values(["Points", "__last"], ascending=[False, False])
    yes = yes.assign(**{"Rank in account": yes.groupby("Account key").cumcount() + 1})
    people = people.drop(columns=["Rank in account"], errors="ignore").merge(
        yes[["__k", "Rank in account"]], on="__k", how="left") if not yes.empty else people.assign(**{"Rank in account": None})
    people["Shown"] = people["Rank in account"].le(top_n).map({True: "Yes", False: ""})
    notes = _account_notes(companies, L, window_start)
    company_visits = companies.apply(lambda r: (match_account(r["Website"], r["CompanyName"], L) or {}).get("group"), axis=1)

    summary = _summary(people, notes, raw, persons, used, newest, top_n, unclear, settled, L, include_names)
    summary["whales"] = _whales(people, company_visits.value_counts().to_dict(), L)
    order = {"RULED OUT": 2, "NO": 1, "YES": 0}
    people = people.sort_values(["Result", "Account tier", "Account", "Points", "__last"],
                                key=lambda s: s.map(order) if s.name == "Result" else s,
                                ascending=[True, True, True, False, False], na_position="last")
    return {"summary": summary, "people": people.drop(columns=["__k", "__last"]), "notes": notes}


def _check_person(k: str, a: dict, role_persona: tuple[str, str], settled: dict, L: Lists, recent_start) -> dict:
    S, r = L.settings, a["rec"]
    title, company = r["Title"], r["CompanyName"]
    strength, persona = role_persona
    settled_by_ai = strength == UNCLEAR and title in settled
    if settled_by_ai:
        strength = settled[title]
    site, email_dom = norm_domain(r["Website"]), r["WorkEmail"].split('@')[-1].lower() if '@' in r["WorkEmail"] else ''

    # WHICH
    acct = match_account(r["Website"], company, L)
    segment = (acct or {}).get("segment", "")
    if acct:
        account, key, tier = acct["group"], "t:" + acct["group"], acct["account_tier"]
        kind = "whale" if "whale" in acct.get("source", "") else ("priority account" if tier == 1 else "target account")
    elif r["EstimateRevenue"] in L.new_logo_revenue and r["Industry"] not in L.new_logo_exclude_industries:
        account, key, tier, kind = company or site, "n:" + (site or company.lower()), 2, "new logo"
    else:
        account, key, tier, kind = company or site, "x:" + (site or company.lower()), None, ""

    # RULE OUT
    out = []
    if _name_hit(company, L.own_names) or _in_domains(email_dom, L.own_domains) or _in_domains(site, L.own_domains):
        out.append("own staff")
    if _name_hit(company, L.competitor_names) or _in_domains(email_dom, L.competitor_domains) or _in_domains(site, L.competitor_domains):
        out.append("competitor")
    personal = email_dom in L.personal_domains
    if acct and ((personal and L.personal_domains[email_dom] and match_account(L.personal_domains[email_dom], '', L) is acct)
                 or site in L.personal_domains):
        out.append("wrong company match (personal email)")
    if STUDENT.search(title):
        out.append("student or job seeker")
    country = locate(r["City"], r["State"], L)
    if country and not L.countries.get(country, False):
        out.append(f"outside focus regions ({country})")

    # WHAT (pages within the visit window only)
    kinds = page_kinds(a["recent_urls"], L)
    strong_interest = bool(kinds.get("contact") or kinds.get("service"))
    strong_role = strength in (LEADS, PRACTITIONER)

    # points: role counts once; page types add up
    pts = []
    if kinds.get("contact"):
        pts.append(("Contact Us", S["points_contact"]))
    if kinds.get("service"):
        pts.append(("service page", S["points_service"]))
    if strength == LEADS:
        pts.append(("leads/buys AI/data", S["points_leads_or_buys"]))
    elif strength == PRACTITIONER:
        pts.append(("AI/data practitioner", S["points_practitioner"]))
    if kinds.get("article"):
        pts.append(("AI article", S["points_article"]))
    first, last = a["first"], a["last"]
    if len(a["days"]) > 1 or (pd.notna(first) and pd.notna(last) and first.date() != last.date()):
        pts.append(("2+ visits", S["points_repeat"]))
    if pd.notna(last) and last >= recent_start:
        pts.append((f"seen in last {S['recent_days']} days", S["points_recent"]))
    points = sum(p for _, p in pts)

    no = []
    if not strong_role:
        no.append({UNCLEAR: "unclear title (not settled)", NO_TITLE: "no title"}.get(strength, "no strong role"))
    if not strong_interest:
        no.append("no Contact Us or solution page" + (" in the visit window" if page_kinds(a["urls"], L) else ""))
    if tier is None:
        no.append("not a Tier 1/2 account")
    result = "RULED OUT" if out else ("YES" if not no else "NO")

    flags = []
    if personal or not email_dom:
        flags.append("find work email")
    if _name_hit(company, L.partner_names) or _in_domains(site, L.partner_domains):
        flags.append("partner company")
    if not country:
        flags.append("region unknown")
    if settled_by_ai:
        flags.append("title settled by AI")

    if tier == 1:
        nxt = "Client-success owner reaches out; check for an open opportunity first"
    elif kind == "new logo":
        nxt = "SDR to qualify (new logo: check ICP fit)"
    else:
        nxt = "SDR to qualify"
    if "find work email" in flags:
        nxt = "Find work email (Apollo / ZoomInfo), then " + (nxt if nxt[:3].isupper() else nxt[0].lower() + nxt[1:])

    links = _sorted_links(a["recent_urls"] or a["urls"], L)
    icp = icp_label(kinds.get("service", []) + kinds.get("article", []), title, segment, L) if result == "YES" else ""
    return {
        "Result": result,
        "Why": " · ".join(f"{n} +{p}" for n, p in pts) + f" = {points}" if result == "YES" else "; ".join(out or no),
        "Points": points if result == "YES" else None,
        "Account tier": tier, "Account": account, "Account type": kind, "ICP": icp,
        "Next step": nxt if result == "YES" else "",
        "Flags": ", ".join(flags),
        "Role": strength, "Persona": persona, "Interest": ", ".join(k for k in ("contact", "service", "article") if kinds.get(k)),
        "Country": country,
        "First Name": r["FirstName"], "Last Name": r["LastName"], "Title": title, "Company": company,
        "Work Email": r["WorkEmail"], "LinkedIn": r["LinkedInUrl"], "City": r["City"], "State": r["State"],
        "Revenue": r["EstimateRevenue"], "Employees": r["EstimatedEmployeeCount"], "Industry": r["Industry"],
        "Visits": a["rows"], "All-Time PV": a["pv"],
        "First Seen": str(first)[:10] if pd.notna(first) else "", "Last Seen": str(last)[:10] if pd.notna(last) else "",
        "Pages": " | ".join(links),
        "Account key": key, "__k": k, "__last": last,
    }


def _account_notes(companies: pd.DataFrame, L: Lists, window_start) -> pd.DataFrame:
    """Company-only visits (no person identified) from Tier 1/2 accounts that opened
    a solution page within the visit window. Target accounts count from any region;
    new logos only from the focus regions and outside the excluded industries."""
    rows = {}
    for _, r in companies.iterrows():
        if pd.isna(r["__last"]) or r["__last"] < window_start:
            continue
        kinds = page_kinds(_paths(r["RecentPageUrls"]), L)
        if not kinds.get("service"):
            continue
        company, site = r["CompanyName"], norm_domain(r["Website"])
        if (_name_hit(company, L.own_names) or _in_domains(site, L.own_domains)
                or _name_hit(company, L.competitor_names) or _in_domains(site, L.competitor_domains)):
            continue
        acct = match_account(r["Website"], company, L)
        if acct:
            key, account, tier = acct["group"], acct["group"], acct["account_tier"]
            kind = "whale" if "whale" in acct.get("source", "") else ("priority account" if tier == 1 else "target account")
        elif r["EstimateRevenue"] in L.new_logo_revenue and r["Industry"] not in L.new_logo_exclude_industries:
            country = locate(r["City"], r["State"], L)
            if not L.countries.get(country, False):
                continue  # a new logo only counts from the focus regions
            key, account, tier, kind = site or company.lower(), company or site, 2, "new logo"
        else:
            continue
        n = rows.setdefault(key, {"Account tier": tier, "Account": account, "Account type": kind, "Visits": 0,
                                  "Solution-page visits": 0, "Contact Us visits": 0, "__pages": [], "__ai_pages": [], "__countries": set(),
                                  "Last Seen": "", "Industry": r["Industry"], "Revenue": r["EstimateRevenue"]})
        n["Visits"] += 1
        n["Solution-page visits"] += bool(kinds.get("service"))
        n["Contact Us visits"] += bool(kinds.get("contact"))
        n["__pages"] += kinds.get("contact", []) + kinds.get("service", [])
        n["__ai_pages"] += kinds.get("service", []) + kinds.get("article", [])
        n["__segment"] = (acct or {}).get("segment", "")
        n["__countries"].add(locate(r["City"], r["State"], L) or "unknown")
        n["Last Seen"] = max(n["Last Seen"], str(r["__last"])[:10])
    out = []
    for n in rows.values():
        pages = list(dict.fromkeys(n.pop("__pages")))
        n["ICP"] = icp_label(n.pop("__ai_pages"), "", n.pop("__segment"), L)
        n["Countries"] = ", ".join(sorted(n.pop("__countries")))
        n["Pages"] = " | ".join(_sorted_links(pages, L))
        n["Next step"] = "Raise with the account team at the next touchpoint"
        out.append(n)
    cols = ["Account tier", "Account", "Account type", "ICP", "Visits", "Solution-page visits", "Contact Us visits",
            "Countries", "Last Seen", "Industry", "Revenue", "Pages", "Next step"]
    df = pd.DataFrame(out, columns=cols)
    return df.sort_values(["Account tier", "Contact Us visits", "Solution-page visits", "Visits"],
                          ascending=[True, False, False, False]).reset_index(drop=True)


# ---------------- summary for the chat (no personal details) ----------------
def _whales(people: pd.DataFrame, company_visits: dict, L: Lists) -> dict:
    """Per whale account: who was seen and why they weren't leads, so "why isn't
    anyone from <account> here?" is answered from counts."""
    out = {}
    for w in sorted({a["group"] for a in L.accounts.values() if "whale" in a.get("source", "")}):
        g = people[people["Account"] == w]
        out[w] = {
            "people_identified": int(len(g)),
            "yes": int((g["Result"] == "YES").sum()),
            "not_leads_by_reason": g[g["Result"] != "YES"]["Why"].str.split("; ").explode().value_counts().to_dict(),
            "company_only_visits": int(company_visits.get(w, 0)),
        }
    return out


def _links(cell: str) -> tuple[list[str], int]:
    """Page links for the chat, without query strings or fragments (the workbook keeps them)."""
    urls = list(dict.fromkeys(u for u in map(page_link, str(cell).split(" | ")) if u))
    return urls[:MAX_LINKS], max(len(urls) - MAX_LINKS, 0)


def _lead(x, include_names: bool) -> dict:
    links, more = _links(x["Pages"])
    item = {
        "rank": int(x["Rank in account"]), "points": int(x["Points"]), "why": x["Why"], "icp": x["ICP"],
        "title": str(x["Title"])[:80], "role": x["Role"], "country": x["Country"] or "unknown",
        "visits": int(x["Visits"]), "last_seen": x["Last Seen"], "flags": x["Flags"],
        "next_step": x["Next step"], "pages": links, "more_pages": more,
    }
    if include_names:
        item["name"] = f"{x['First Name']} {x['Last Name']}".strip()
    return item


def _note(n) -> dict:
    links, more = _links(n["Pages"])
    return {"account": n["Account"], "account_type": n["Account type"], "icp": n["ICP"], "visits": int(n["Visits"]),
            "solution_page_visits": int(n["Solution-page visits"]), "contact_us_visits": int(n["Contact Us visits"]),
            "countries": n["Countries"], "last_seen": n["Last Seen"], "pages": links, "more_pages": more,
            "next_step": n["Next step"]}


def _summary(people, notes, raw, persons, used, newest, top_n, unclear, settled, L, include_names) -> dict:
    S = L.settings
    yes = people[people["Result"] == "YES"]
    shown = yes[yes["Shown"] == "Yes"]
    tiers = {}
    for t in (1, 2):
        accts = []
        sub = shown[shown["Account tier"] == t]
        best = sub.groupby("Account key")["Points"].max().sort_values(ascending=False)
        for key in best.index:
            g = sub[sub["Account key"] == key].sort_values("Rank in account")
            n_yes = int((yes["Account key"] == key).sum())
            accts.append({"account": g["Account"].iloc[0], "account_type": g["Account type"].iloc[0],
                          "yes_total": n_yes, "leads": [_lead(x, include_names) for _, x in g.iterrows()]})
        tiers[f"tier_{t}"] = accts
    whales = sorted({a["group"] for a in L.accounts.values() if "whale" in a.get("source", "")})
    active = set(shown["Account"]) | set(notes.loc[notes["Account tier"] == 1, "Account"])
    ruled = people[people["Result"] == "RULED OUT"]["Why"].str.split("; ").explode()
    ruled = ruled.str.replace(r' \(.*\)$', '', regex=True).value_counts().to_dict()
    no = people[people["Result"] == "NO"]["Why"].str.split("; ").explode().value_counts().to_dict()
    n2 = int(S["max_account_notes_tier_2"])
    t1n, t2n = notes[notes["Account tier"] == 1], notes[notes["Account tier"] == 2]
    return {
        "file": {
            "input_files": used, "rows": len(raw), "people_identified": int(len(people)),
            "person_rows": int(len(persons)), "company_only_rows": int(len(raw) - len(persons)),
            "newest_visit": str(newest)[:10],
            "visit_window": f"{S['window_days']} days to {str(newest)[:10]}",
        },
        "counts": {
            "yes": int(len(yes)), "shown": int(len(shown)), "accounts_with_leads": int(shown["Account key"].nunique()),
            "no": int((people["Result"] == "NO").sum()), "ruled_out": int((people["Result"] == "RULED OUT").sum()),
            "account_notes": int(len(notes)),
            "yes_by_icp": yes["ICP"].value_counts().to_dict() if "ICP" in yes else {},
        },
        "tier_1": tiers["tier_1"], "tier_2": tiers["tier_2"],
        "quiet_whales": [w for w in whales if w not in active],
        "account_notes": {"tier_1": [_note(n) for _, n in t1n.iterrows()],
                          "tier_2": [_note(n) for _, n in t2n.head(n2).iterrows()],
                          "tier_2_total": int(len(t2n))},
        "ruled_out_by_reason": ruled,
        "left_out_by_reason": no,
        "unclear_titles": {"distinct_titles": len(unclear), "settled_by_ai": len(settled),
                           "people_left_out": int(no.get("unclear title (not settled)", 0))},
        "settings": {"top_n": top_n, **{k: v for k, v in S.items() if k.startswith("points_")},
                     "window_days": S["window_days"], "recent_days": S["recent_days"]},
        "names_included": include_names,
    }
