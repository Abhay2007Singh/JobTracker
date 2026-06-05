# Orchestrates the full classification pipeline for a single email.
# Combines rule-based pre-filtering, Gemini extraction, and validation
# into one call: extract(email) → ExtractedData | None.

from typing import Optional

from app.classifier.types import ExtractedData
from app.classifier.rules import classify_by_rules, RulesResult
from app.classifier.gemini import GeminiClassifier
from app.classifier.validator import validate_and_normalise
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_gemini = GeminiClassifier()

# Rules confidence above this threshold is trusted without Gemini verification
_HIGH_CONFIDENCE = 0.80


def extract(email: dict) -> Optional[ExtractedData]:
    """
    Classification + extraction pipeline for a single parsed email dict.

    Pipeline:
      1. Rule-based classifier (fast, no API call).
         - High-confidence IRRELEVANT → drop immediately, return None.
         - Otherwise, pass category hint to Gemini.
      2. Gemini classifier + extractor (API call).
         - Returns structured JSON with category + all fields.
         - On Gemini failure, falls back to rules result if available.
      3. Post-Gemini irrelevant check → return None.
      4. Validator normalises the raw dict.
      5. Return ExtractedData.
    """
    email_id = email.get("email_id", "?")

    # ── Step 1: rule-based pre-filter ─────────────────────────────────────────
    rules: RulesResult = classify_by_rules(email)

    if rules.is_irrelevant and rules.confidence >= _HIGH_CONFIDENCE:
        logger.info(f"[{email_id}] Dropped as IRRELEVANT by rules (conf={rules.confidence:.2f})")
        return None

    rules_hint = (
        f"category={rules.category}, platform={rules.platform}, confidence={rules.confidence:.2f}"
        if rules.category not in ("UNCERTAIN", "IRRELEVANT")
        else "none"
    )

    # ── Step 2: Gemini classification + extraction ─────────────────────────────
    gemini_raw: Optional[dict] = _gemini.classify_and_extract(email, rules_hint=rules_hint)

    if gemini_raw is None:
        if rules.category not in ("UNCERTAIN", "IRRELEVANT"):
            # Gemini failed but rules gave us something — use rules as fallback
            logger.warning(f"[{email_id}] Gemini failed — falling back to rules result")
            gemini_raw = {
                "category":            rules.category,
                "company":             None,
                "role":                None,
                "platform":            rules.platform,
                "location":            None,
                "salary_range":        None,
                "job_url":             None,
                "confidence":          rules.confidence,
                "description_snippet": email.get("snippet"),
            }
        else:
            logger.warning(f"[{email_id}] Gemini failed and rules uncertain — skipping email")
            return None

    # ── Step 3: post-Gemini irrelevant check ──────────────────────────────────
    if gemini_raw.get("category") == "IRRELEVANT":
        logger.info(f"[{email_id}] Marked IRRELEVANT by Gemini")
        return None

    # ── Step 4: validate and normalise ────────────────────────────────────────
    clean = validate_and_normalise(email, gemini_raw, rules.platform)
    if clean is None:
        logger.warning(f"[{email_id}] Validation returned None — skipping")
        return None

    # ── Step 5: build ExtractedData ───────────────────────────────────────────
    logger.info(
        f"[{email_id}] Extracted: category={clean['category']} "
        f"company={clean['company']!r} role={clean['role']!r} "
        f"platform={clean['platform']} conf={clean['confidence']:.2f}"
    )

    return ExtractedData(
        email_id=clean["email_id"],
        email_subject=clean["email_subject"],
        email_date=clean["email_date"],
        email_sender=clean["email_sender"],
        category=clean["category"],
        company=clean["company"],
        role=clean["role"],
        platform=clean["platform"],
        job_url=clean["job_url"],
        location=clean["location"],
        salary_range=clean["salary_range"],
        job_description_snippet=clean["job_description_snippet"],
        confidence=clean["confidence"],
    )
