# Validates and normalises the raw dict returned by Gemini before it becomes ExtractedData.
# Returns a clean dict on success, or None if the data is unusable.

import re
from datetime import datetime
from typing import Optional

from app.models.application import Platform
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

VALID_CATEGORIES = {
    "APPLICATION_CONFIRMATION",
    "INTERVIEW_INVITATION",
    "JOB_OFFER",
    "REJECTION",
    "STATUS_UPDATE",
}

VALID_PLATFORMS = {p.value for p in Platform}

# Strips generic corporate suffixes to keep company names clean
_COMPANY_NOISE = re.compile(
    r"\s*\b(inc\.?|ltd\.?|llc\.?|pvt\.?|private\s+limited|limited|"
    r"technologies|tech|solutions|services|software|systems|consulting|group)\b\s*",
    re.IGNORECASE,
)


def validate_and_normalise(email: dict, gemini_raw: dict, rules_platform: str) -> Optional[dict]:
    """
    Takes the raw Gemini output dict and the source email dict.
    Returns a clean, validated dict suitable for constructing ExtractedData,
    or None if the result is fundamentally unusable.
    """
    category = gemini_raw.get("category") or "STATUS_UPDATE"
    if category not in VALID_CATEGORIES:
        logger.warning(f"Unknown category '{category}' — defaulting to STATUS_UPDATE")
        category = "STATUS_UPDATE"

    company = _clean_company(gemini_raw.get("company") or "Unknown")
    role    = _clean_role(gemini_raw.get("role") or "Unknown")

    platform = gemini_raw.get("platform") or rules_platform
    if platform not in VALID_PLATFORMS:
        platform = Platform.UNKNOWN.value

    location     = _clean_str(gemini_raw.get("location"))
    salary_range = _clean_salary(gemini_raw.get("salary_range"))
    job_url      = _clean_url(gemini_raw.get("job_url"))

    snippet = _clean_str(gemini_raw.get("description_snippet") or email.get("snippet"))
    if snippet:
        snippet = snippet[:500]

    confidence = _clamp_float(gemini_raw.get("confidence"), default=0.5)

    email_date = email.get("date")
    if not isinstance(email_date, datetime):
        email_date = datetime.utcnow()

    return {
        "email_id":                email["email_id"],
        "email_subject":           email.get("subject", ""),
        "email_date":              email_date,
        "email_sender":            email.get("sender", ""),
        "category":                category,
        "company":                 company,
        "role":                    role,
        "platform":                platform,
        "job_url":                 job_url,
        "location":                location,
        "salary_range":            salary_range,
        "job_description_snippet": snippet,
        "confidence":              confidence,
    }


# ── field-level cleaners ──────────────────────────────────────────────────────

def _clean_company(name: str) -> str:
    name = _COMPANY_NOISE.sub(" ", name).strip(" ,.-")
    return name.strip() or "Unknown"


def _clean_role(role: str) -> str:
    return role.strip().title() or "Unknown"


def _clean_str(val) -> Optional[str]:
    if not val:
        return None
    s = str(val).strip()
    if s.lower() in ("null", "none", "n/a", "na", ""):
        return None
    return s


def _clean_salary(val) -> Optional[str]:
    s = _clean_str(val)
    if not s:
        return None
    # Accept only if it looks like a salary (contains digits)
    if not re.search(r"\d", s):
        return None
    return s


def _clean_url(val) -> Optional[str]:
    s = _clean_str(val)
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        return None
    # Basic sanity — must have at least one dot after scheme
    if "." not in s[8:]:
        return None
    return s


def _clamp_float(val, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(val)))
    except (TypeError, ValueError):
        return default
