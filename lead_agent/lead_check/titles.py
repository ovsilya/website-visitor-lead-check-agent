"""The "who" check: how strong a visitor's role is, from the job title alone.

Returns one of four strengths:
  leads or buys AI/data   (+2 points)  heads/directors/VPs/chiefs of AI, ML or data,
                                       technology chiefs, engineering leaders, procurement
  AI/data practitioner    (+1 point)   ML engineers, data scientists, AI researchers
  unclear                              settled later from the title text (e.g. "Research Scientist")
  not a strong role                    sellers, recruiters, unrelated functions, generic seniority

Seniority alone is never enough: "VP Sales" at a target account is not a lead.
This is a simplified, self-contained rule set written for the portfolio version.
"""
import re


def W(*words: str) -> re.Pattern:
    """Whole-word, case-insensitive match for any of the words or phrases."""
    return re.compile(r"(?<![a-z])(?:" + "|".join(words) + r")(?![a-z])", re.I)


SELLER = W("sales", "seller", "account executive", "account manager", "business development", "bdr", "sdr",
           "recruiter", "recruiting", "talent", "marketing", "brand", "communications", "customer success",
           "partnerships", "go-to-market", "gtm")
AI = W("ai", "a\\.i\\.", "ml", "machine learning", "artificial intelligence", "deep learning", "genai", "generative",
       "llm", "nlp", "computer vision", "robotics", "autonomy", "autonomous", "perception", "foundation models?",
       "reinforcement learning", "ai safety", "alignment", "model evaluation", "evaluation")
DATA = W("data", "data science", "analytics", "data platform")
RESEARCH = W("research scientist", "research engineer", "researcher", "scientist", "applied scientist")
PRACTICE = W("engineer", "engineering", "developer", "scientist", "researcher", "architect", "mle")
LEADER = W("head", "director", "vp", "vice president", "svp", "evp", "chief", "manager", "lead", "leader",
           "principal")
TECH_CHIEF = W("cto", "cio", "cdo", "caio", "chief technology officer", "chief data officer",
               "chief ai officer", "chief scientist", "chief information officer")
TECH_LEADER = W("engineering", "technology", "platform", "infrastructure")
SENIOR = W("head", "director", "vp", "vice president", "svp", "evp")
PROCUREMENT = W("procurement", "sourcing", "purchasing", "vendor management", "category manager")
FOUNDER = W("founder", "co-founder", "cofounder", "ceo", "owner", "president")
NOT_CORPORATE = W("funeral director", "athletic director", "art director", "creative director", "head coach",
                  "head chef", "head teacher")

LEADS, PRACTITIONER, UNCLEAR, WEAK, NO_TITLE = (
    "leads or buys AI/data", "AI/data practitioner", "unclear", "not a strong role", "no title")


def role(title: str) -> tuple[str, str]:
    """(role strength, persona) for a job title."""
    t = title.strip()
    if not t:
        return NO_TITLE, "Untitled - needs enrichment"
    if SELLER.search(t) or NOT_CORPORATE.search(t):
        return WEAK, "Non-AI/Data"
    ai, data = bool(AI.search(t)), bool(DATA.search(t))
    if PROCUREMENT.search(t):
        return LEADS, "Procurement"
    if TECH_CHIEF.search(t):
        return LEADS, "Technology leadership"
    if (ai or data) and LEADER.search(t):
        return LEADS, "AI/Data leadership"
    if SENIOR.search(t) and TECH_LEADER.search(t):
        return LEADS, "Engineering leadership"
    if RESEARCH.search(t) and not ai and not data:
        return UNCLEAR, "Researcher (field unclear)"   # ML or life sciences? settled later
    if ai or (data and PRACTICE.search(t)):
        return PRACTITIONER, "AI/Data practitioner"
    if data:
        return UNCLEAR, "Data / Analytics"             # "Data Analyst" at a bank vs a data lead at a lab
    if FOUNDER.search(t):
        return UNCLEAR, "Founder / owner"              # a startup founder can be the buyer
    return WEAK, "Non-AI/Data"
