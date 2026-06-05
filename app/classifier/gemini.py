# Gemini AI classifier — sends the email to Gemini and extracts structured JSON data.
# Called only when the rule-based classifier is uncertain or needs data extraction.

import json
import re
import time
from typing import Optional

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_SYSTEM_CONTEXT = (
    "You are an AI assistant that extracts structured data from job application emails.\n"
    "User context: Python Backend Developer / SDE Intern applicant, based in Bangalore, India.\n"
    f"Target roles: {', '.join(config.TARGET_ROLES)}.\n"
    "Salary format: INR LPA (e.g. '8-12 LPA'). Date format: DD/MM/YYYY."
)

_PROMPT_TEMPLATE = """\
Analyse this job-related email and return ONLY a valid JSON object — no markdown, no explanation.

Email Subject : {subject}
Email Sender  : {sender}
Email Body    :
{body}

Hints from rule-based pre-filter: {rules_hint}

Return exactly this JSON structure:
{{
  "category"            : "<APPLICATION_CONFIRMATION | INTERVIEW_INVITATION | JOB_OFFER | REJECTION | STATUS_UPDATE | IRRELEVANT>",
  "company"             : "<company name or null>",
  "role"                : "<job title or null>",
  "platform"            : "<LinkedIn | Naukri | Wellfound | Internshala | Indeed | Direct | Referral | Unknown>",
  "location"            : "<city, state, or Remote — or null>",
  "salary_range"        : "<e.g. 8-12 LPA — or null>",
  "job_url"             : "<direct URL to job post from email body — or null>",
  "confidence"          : <float 0.0-1.0>,
  "description_snippet" : "<first 200 chars of job description if present — else null>"
}}

Category definitions:
  IRRELEVANT             — newsletter, job alert digest, promotional, no specific action
  APPLICATION_CONFIRMATION — confirms your application was received
  INTERVIEW_INVITATION   — invites you to interview, assessment, coding challenge, or call
  JOB_OFFER              — extends a formal job or internship offer
  REJECTION              — informs you that you were not selected
  STATUS_UPDATE          — any other status update about an in-progress application
"""


_MIN_CALL_INTERVAL = 5.0   # seconds between Gemini calls (caps at 12/min, limit is 15/min)
_RATE_LIMIT_RESET  = 65.0  # seconds to wait after a 429 (resets the 60-second quota window)


class GeminiClassifier:

    _last_call_time: float = 0.0   # shared across all instances

    def __init__(self) -> None:
        self._client = None

    def _client_instance(self):
        if self._client is None:
            from google import genai  # lazy import — avoids import error if package missing
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._client

    def _throttle(self) -> None:
        """Enforces a minimum interval between API calls to stay under free-tier RPM."""
        elapsed = time.time() - GeminiClassifier._last_call_time
        if elapsed < _MIN_CALL_INTERVAL:
            time.sleep(_MIN_CALL_INTERVAL - elapsed)

    def _call_with_retry(self, prompt: str, max_retries: int = 3) -> Optional[str]:
        for attempt in range(max_retries):
            self._throttle()
            try:
                GeminiClassifier._last_call_time = time.time()
                response = self._client_instance().models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=prompt,
                )
                return response.text
            except Exception as exc:
                err = str(exc).lower()
                if any(kw in err for kw in ("quota", "429", "rate limit", "resource_exhausted")):
                    # Wait long enough to escape the current 60-second quota window
                    wait = _RATE_LIMIT_RESET * (attempt + 1)  # 65 s → 130 s → 195 s
                    logger.warning(f"Gemini rate limit — waiting {wait:.0f}s (attempt {attempt + 1}/{max_retries})")
                    time.sleep(wait)
                else:
                    logger.error(f"Gemini API error: {exc}")
                    return None
        logger.error("Gemini max retries exceeded")
        return None

    def classify_and_extract(self, email: dict, rules_hint: str = "none") -> Optional[dict]:
        """
        Calls Gemini to classify the email and extract all structured fields.
        Returns a raw dict (keys per _PROMPT_TEMPLATE) or None on failure.
        """
        prompt = (
            _SYSTEM_CONTEXT
            + "\n\n"
            + _PROMPT_TEMPLATE.format(
                subject=email.get("subject", ""),
                sender=email.get("sender", ""),
                body=(email.get("body") or "")[:3000],
                rules_hint=rules_hint,
            )
        )

        raw_text = self._call_with_retry(prompt)
        if not raw_text:
            return None

        parsed = _parse_json(raw_text)
        if parsed is None:
            logger.warning(f"Gemini returned unparseable response for {email.get('email_id', '?')}: {raw_text[:200]}")
        return parsed


# ── JSON parsing helper ────────────────────────────────────────────────────────

def _parse_json(text: str) -> Optional[dict]:
    """Extracts a JSON object from Gemini's response, handling markdown fences."""
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*",     "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to grab the first {...} block in case of extra prose
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None
