# Rule-based email classifier — fast keyword and sender-domain matching.
# Used before calling Gemini to drop obvious noise and provide classification hints.

import re
from dataclasses import dataclass

from app.models.application import Platform

# ── sender-domain → Platform mapping ─────────────────────────────────────────

PLATFORM_SENDER_MAP: dict[str, str] = {
    "linkedin.com":          Platform.LINKEDIN.value,
    "naukri.com":            Platform.NAUKRI.value,
    "wellfound.com":         Platform.WELLFOUND.value,
    "angel.co":              Platform.WELLFOUND.value,
    "internshala.com":       Platform.INTERNSHALA.value,
    "indeed.com":            Platform.INDEED.value,
    "lever.co":              Platform.DIRECT.value,
    "greenhouse.io":         Platform.DIRECT.value,
    "workday.com":           Platform.DIRECT.value,
    "myworkday.com":         Platform.DIRECT.value,
    "myworkdayjobs.com":     Platform.DIRECT.value,
    "smartrecruiters.com":   Platform.DIRECT.value,
    "taleo.net":             Platform.DIRECT.value,
    "icims.com":             Platform.DIRECT.value,
    "successfactors.com":    Platform.DIRECT.value,
    "brassring.com":         Platform.DIRECT.value,
    "bamboohr.com":          Platform.DIRECT.value,
    "instahyre.com":         Platform.DIRECT.value,
    "cutshort.io":           Platform.DIRECT.value,
    "hirist.com":            Platform.HIRIST.value,
    "hirist.tech":           Platform.HIRIST.value,
    "jooble.org":            Platform.JOOBLE.value,
    "jobsora.com":           Platform.JOBSORA.value,
    "nttdata.com":           Platform.DIRECT.value,
}

# ── noise / irrelevant patterns (checked on subject line) ────────────────────

_IRRELEVANT = [
    r"\bjob alert\b",
    r"\bjobs? for you\b",
    r"\brecommended jobs?\b",
    r"\bpeople are hiring\b",
    r"\bnew jobs?\b.{0,30}\bmatching\b",
    r"\bweekly digest\b",
    r"\bnewsletter\b",
    r"\bsubscription\b",
    r"\bunsubscribe\b",
    r"\bpromotion\b",
    r"\bspecial offer\b",
    r"\blearn (python|coding|programming)\b",
    r"\b(online )?course\b",
    r"\bwebinar\b",
    r"\bsalary insights?\b",
    r"\bmarket report\b",
    r"\btop companies hiring\b",
    r"\bexplore jobs?\b",
    r"\bjobs? in (india|bangalore|remote)\b",
    r"\bprofile views?\b",
    r"\bconnection request\b",
]

# ── category patterns (checked on subject, then body) ────────────────────────

_CONFIRMATION = [
    r"application received",
    r"application submitted",
    r"you (have )?applied",
    r"we received your application",
    r"thank(s| you) for (applying|your application|your interest|submitting|your submission)",
    r"thank(s| you) for your (online )?submission",
    r"application for .{0,60} (position|role|job)",
    r"successfully submitted",
    r"has been submitted",
    r"online submission",
]

_INTERVIEW = [
    r"\binterview\b",
    r"schedule (a |your )?(call|meeting|chat|interview)",
    r"coding challenge",
    r"technical (assessment|round|test|interview)",
    r"online (assessment|test|exam)",
    r"next (steps?|round)",
    r"\bshortlisted\b",
    r"\baptitude test\b",
    r"\bhackerrank\b",
    r"\bhackerearth\b",
    r"\bcodility\b",
    r"\bcodesignal\b",
    r"you('ve| have) been selected for",
]

_OFFER = [
    r"offer letter",
    r"\bjob offer\b",
    r"pleased to offer",
    r"congratulations.{0,40}offer",
    r"we would like to offer",
    r"extend(ing)? (an |our )?offer",
    r"salary (package|details)",
]

_REJECTION = [
    r"regret to inform",
    r"unfortunately",
    r"not (moving|proceeding) forward",
    r"decided to (move forward|proceed) with other",
    r"position has been filled",
    r"not (selected|shortlisted|successful)",
    r"we (will not|cannot|won't) be",
    r"other candidates",
    r"thank you for your time.{0,60}not",
]

# Ordered by specificity — interview before confirmation so "interview confirmation" hits interview
_CATEGORY_PATTERNS: list[tuple[str, list[str]]] = [
    ("INTERVIEW_INVITATION",     _INTERVIEW),
    ("JOB_OFFER",                _OFFER),
    ("REJECTION",                _REJECTION),
    ("APPLICATION_CONFIRMATION", _CONFIRMATION),
]


@dataclass
class RulesResult:
    category:     str    # EmailCategory value, "UNCERTAIN", or "IRRELEVANT"
    platform:     str    # Platform value
    confidence:   float  # 0.0 – 1.0
    is_irrelevant: bool


def classify_by_rules(email: dict) -> RulesResult:
    """
    Classifies an email using regex patterns only — no API calls.
    Returns RulesResult with the best-guess category, platform, and confidence.
    """
    subject = (email.get("subject") or "").lower()
    sender  = (email.get("sender")  or "").lower()
    body    = (email.get("body")    or "").lower()[:1500]

    # Platform from sender domain
    platform = Platform.UNKNOWN.value
    for domain, plat in PLATFORM_SENDER_MAP.items():
        if domain in sender:
            platform = plat
            break

    # Quick irrelevant check on subject
    for pattern in _IRRELEVANT:
        if re.search(pattern, subject, re.IGNORECASE):
            return RulesResult(category="IRRELEVANT", platform=platform, confidence=0.90, is_irrelevant=True)

    # Category match — subject first (high confidence)
    for category, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, subject, re.IGNORECASE):
                return RulesResult(category=category, platform=platform, confidence=0.85, is_irrelevant=False)

    # Category match — body scan (lower confidence)
    for category, patterns in _CATEGORY_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, body, re.IGNORECASE):
                return RulesResult(category=category, platform=platform, confidence=0.55, is_irrelevant=False)

    return RulesResult(category="UNCERTAIN", platform=platform, confidence=0.0, is_irrelevant=False)
