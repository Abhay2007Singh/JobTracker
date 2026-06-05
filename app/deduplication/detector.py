# Duplicate detection — three-tier check: exact email ID, same job URL, fuzzy company+role.
# Uses only stdlib difflib — no extra dependencies.

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy.orm import Session

from app.classifier.types import ExtractedData
from app.models.application import Application
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Fuzzy-match thresholds
_COMPANY_SIM_THRESHOLD = 0.85
_ROLE_SIM_THRESHOLD    = 0.75

# Only compare against applications created in the last N days
_LOOKBACK_DAYS = 60


@dataclass
class DuplicateResult:
    is_duplicate:    bool
    duplicate_of_id: Optional[int]
    reason:          str   # "exact_email_id" | "same_job_url" | "fuzzy_match" | "none"
    details:         str   # human-readable explanation for Telegram notification


def check_duplicate(db: Session, extracted: ExtractedData) -> DuplicateResult:
    """
    Runs three duplicate checks in order of cheapness.

    1. Exact email_id match  — same Gmail message already in DB
    2. Same job_url match    — two emails pointing to the same job posting
    3. Fuzzy company + role  — similar company AND similar role within last 60 days

    Returns DuplicateResult. The caller decides whether to save with is_duplicate=True
    or ask the user via Telegram.
    """

    # ── 1. Exact email ID ─────────────────────────────────────────────────────
    existing = (
        db.query(Application)
        .filter(Application.email_id == extracted.email_id)
        .first()
    )
    if existing:
        logger.info(f"[{extracted.email_id}] Exact duplicate → DB id={existing.id}")
        return DuplicateResult(
            is_duplicate=True,
            duplicate_of_id=existing.id,
            reason="exact_email_id",
            details=f"This exact email was already processed (id={existing.id}).",
        )

    # ── 2. Same job URL ───────────────────────────────────────────────────────
    if extracted.job_url:
        url_match = (
            db.query(Application)
            .filter(
                Application.job_url == extracted.job_url,
                Application.is_duplicate.is_(False),
            )
            .first()
        )
        if url_match:
            logger.info(f"[{extracted.email_id}] Same job URL → DB id={url_match.id}")
            return DuplicateResult(
                is_duplicate=True,
                duplicate_of_id=url_match.id,
                reason="same_job_url",
                details=(
                    f"Same job URL already tracked as id={url_match.id} "
                    f"({url_match.company} — {url_match.role})."
                ),
            )

    # ── 3. Fuzzy company + role ───────────────────────────────────────────────
    cutoff = datetime.utcnow() - timedelta(days=_LOOKBACK_DAYS)
    recent = (
        db.query(Application)
        .filter(
            Application.created_at >= cutoff,
            Application.is_duplicate.is_(False),
        )
        .all()
    )

    norm_company = _normalize(extracted.company)
    norm_role    = _normalize(extracted.role)

    for app in recent:
        co_sim   = _similarity(_normalize(app.company), norm_company)
        role_sim = _similarity(_normalize(app.role),    norm_role)

        if co_sim >= _COMPANY_SIM_THRESHOLD and role_sim >= _ROLE_SIM_THRESHOLD:
            logger.info(
                f"[{extracted.email_id}] Fuzzy duplicate → DB id={app.id} "
                f"'{app.company}/{app.role}' "
                f"(co_sim={co_sim:.2f}, role_sim={role_sim:.2f})"
            )
            return DuplicateResult(
                is_duplicate=True,
                duplicate_of_id=app.id,
                reason="fuzzy_match",
                details=(
                    f"Likely duplicate of id={app.id}: {app.company} — {app.role} "
                    f"(company match {co_sim:.0%}, role match {role_sim:.0%})."
                ),
            )

    return DuplicateResult(
        is_duplicate=False,
        duplicate_of_id=None,
        reason="none",
        details="No duplicate found.",
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """
    Lowercase, strip corporate noise words, remove punctuation,
    collapse whitespace — so 'Google LLC' and 'Google' compare as equal.
    """
    text = text.lower()
    text = re.sub(
        r"\b(pvt|ltd|llc|inc|co\.?|corp|technologies|tech|solutions|"
        r"services|software|systems|consulting|group|india|"
        r"bangalore|bengaluru|private\s+limited|limited)\b",
        " ",
        text,
    )
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
