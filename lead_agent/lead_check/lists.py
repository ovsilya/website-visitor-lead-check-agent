"""Marketing's editable lists for the lead check (the CSV files in lists/).

Everything Marketing may want to change without a code change lives in a CSV:
accounts and tiers, own companies, competitors, partners, interest pages,
ICP labels, regions and the point weights. See lists/README.md.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

LISTS_DIR = Path(os.environ.get("LEAD_CHECK_LISTS", Path(__file__).with_name("lists")))


def _rows(name: str, d: Path) -> list[dict]:
    with open(d / name, newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def _num(v: str):
    try:
        return int(v)
    except ValueError:
        return v


@dataclass
class Lists:
    accounts: dict[str, dict]            # domain -> {account, group, segment, account_tier}
    aliases: dict[str, str]              # alias domain -> account domain
    company_names: dict[str, str]        # normalised company name -> account domain
    own_names: list[str]
    own_domains: set[str]
    competitor_names: list[str]
    competitor_domains: set[str]
    partner_names: list[str]
    partner_domains: set[str]
    personal_domains: dict[str, str]     # personal email domain -> provider's company domain ('' if none)
    pages: list[tuple[str, re.Pattern]]  # (kind, pattern) on the page path
    icp: list[tuple[str, str, re.Pattern]]  # (ICP label, page / title / segment, pattern)
    countries: dict[str, bool]           # country -> in a focus region
    state_codes: dict[str, str]
    cities: dict[tuple[str, str], str]   # (city, state or '') -> country
    settings: dict = field(default_factory=dict)

    @property
    def new_logo_revenue(self) -> set[str]:
        return {v.strip() for v in str(self.settings["new_logo_revenue"]).split("|")}

    @property
    def new_logo_exclude_industries(self) -> set[str]:
        return {v.strip() for v in str(self.settings.get("new_logo_exclude_industries", "")).split("|") if v.strip()}


def load_lists(d: Path | str | None = None) -> Lists:
    d = Path(d or LISTS_DIR)
    kinds = lambda name: _rows(name, d)
    own, comp, part = kinds("own_companies.csv"), kinds("competitors.csv"), kinds("partners.csv")
    by = lambda rows, k: [r["value"].lower() for r in rows if r["kind"] == k and r["value"]]
    return Lists(
        accounts={
            r["domain"].lower(): {**r, "account_tier": int(r["account_tier"])}
            for r in kinds("accounts.csv") if r["domain"]
        },
        aliases={r["alias_domain"].lower(): r["domain"].lower() for r in kinds("account_aliases.csv")},
        company_names={r["company_name"].lower(): r["domain"].lower() for r in kinds("company_names.csv")},
        own_names=by(own, "name"), own_domains=set(by(own, "domain")),
        competitor_names=by(comp, "name"), competitor_domains=set(by(comp, "domain")),
        partner_names=by(part, "name"), partner_domains=set(by(part, "domain")),
        personal_domains={r["domain"].lower(): r["provider_domain"].lower() for r in kinds("personal_email_domains.csv")},
        pages=[(r["kind"], re.compile(r["pattern"], re.I)) for r in kinds("pages.csv")],
        icp=[(r["icp"], r["kind"], re.compile(r["pattern"], re.I)) for r in kinds("icp.csv")],
        countries={r["country"]: r["focus"].lower() == "yes" for r in kinds("countries.csv")},
        state_codes={r["code"].upper(): r["country"] for r in kinds("state_codes.csv")},
        cities={(r["city"].lower(), r["state"].upper()): r["country"] for r in kinds("cities.csv")},
        settings={r["setting"]: _num(r["value"]) for r in kinds("settings.csv")},
    )
