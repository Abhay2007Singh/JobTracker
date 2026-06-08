# Gmail inbox poller — fetches new job-related emails, labels them, and returns
# parsed email dicts ready for the classification pipeline.

import base64
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

from googleapiclient.errors import HttpError

from app.config import config
from app.gmail.auth import get_gmail_service
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Persists the Unix timestamp of the last successful poll so we only fetch new mail.
# Stored next to run.py in the project root.
STATE_FILE = Path("jobtracker_state.json")

# Search query: AND logic — email must match both from: AND subject: conditions.
# This prevents noise from non-job emails that happen to use job-related words.
_JOB_QUERY = (
    "from:(linkedin.com OR naukri.com OR wellfound.com OR internshala.com OR "
    "indeed.com OR angel.co OR angellist.com OR instahyre.com OR cutshort.io OR "
    "hirist.com OR greenhouse.io OR lever.co OR workday.com OR myworkday.com OR "
    "smartrecruiters.com OR bamboohr.com OR icims.com OR taleo.net OR successfactors.com) "
    'subject:("application received" OR "application submitted" OR "you applied" OR '
    '"we received your application" OR "thank you for applying" OR '
    '"application successful" OR "successfully applied" OR "application complete" OR '
    '"thank you for submitting" OR "interview invitation" OR "interview request" OR '
    '"job offer" OR "offer letter" OR "we regret to inform" OR "unfortunately" OR '
    '"shortlisted" OR "next steps" OR "coding challenge" OR "technical assessment")'
)


class GmailPoller:

    def __init__(self) -> None:
        self._service  = None
        self._label_id: Optional[str] = None

    # ── private helpers ──────────────────────────────────────────────────────

    def _svc(self):
        if self._service is None:
            self._service = get_gmail_service()
        return self._service

    def _load_last_poll_ts(self) -> Optional[int]:
        if STATE_FILE.exists():
            try:
                return json.loads(STATE_FILE.read_text(encoding="utf-8")).get("last_poll_unix")
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _save_last_poll_ts(self, ts: int) -> None:
        STATE_FILE.write_text(json.dumps({"last_poll_unix": ts}, indent=2), encoding="utf-8")

    def _ensure_label(self) -> str:
        """Returns the label ID for config.GMAIL_LABEL, creating it if absent."""
        if self._label_id:
            return self._label_id

        labels = self._svc().users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label["name"] == config.GMAIL_LABEL:
                self._label_id = label["id"]
                return self._label_id

        created = self._svc().users().labels().create(
            userId="me",
            body={
                "name": config.GMAIL_LABEL,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        self._label_id = created["id"]
        logger.info(f"Created Gmail label '{config.GMAIL_LABEL}' (id={self._label_id})")
        return self._label_id

    def _extract_body(self, payload: dict) -> str:
        """Recursively extracts plain text from a Gmail message payload."""
        mime = payload.get("mimeType", "")

        if mime == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")

        if mime == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
                return _strip_html(html)

        if mime.startswith("multipart/"):
            parts = payload.get("parts", [])
            # Prefer plain text
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    return self._extract_body(part)
            # Fall back to HTML
            for part in parts:
                if part.get("mimeType") == "text/html":
                    return self._extract_body(part)
            # Recurse into nested multipart (e.g. multipart/mixed inside multipart/alternative)
            for part in parts:
                result = self._extract_body(part)
                if result.strip():
                    return result

        return ""

    def _parse_message(self, raw: dict) -> dict:
        """Converts a raw Gmail API message into a clean dict for classification."""
        payload = raw.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}

        subject  = headers.get("subject", "(no subject)")
        sender   = headers.get("from", "")
        date_str = headers.get("date", "")

        try:
            email_date = parsedate_to_datetime(date_str)
            if email_date.tzinfo is None:
                email_date = email_date.replace(tzinfo=timezone.utc)
        except Exception:
            email_date = datetime.now(timezone.utc)

        body = self._extract_body(payload)

        return {
            "email_id": raw["id"],
            "subject":  subject,
            "sender":   sender,
            "date":     email_date,
            "body":     body[:4000],   # cap for AI — avoids token blowout
            "snippet":  raw.get("snippet", ""),
        }

    def _apply_label(self, msg_id: str, label_id: str) -> None:
        body: dict = {"addLabelIds": [label_id]}
        if config.GMAIL_AUTO_MARK_READ:
            body["removeLabelIds"] = ["UNREAD"]
        self._svc().users().messages().modify(userId="me", id=msg_id, body=body).execute()

    # ── public interface ─────────────────────────────────────────────────────

    def poll(self) -> list[dict]:
        """
        Fetches job-related emails received since the last poll.
        Applies the JobTracker Gmail label to each processed message.
        Returns a list of parsed email dicts for the classification pipeline.
        """
        label_id = self._ensure_label()
        now_ts   = int(datetime.now(timezone.utc).timestamp())
        last_ts  = self._load_last_poll_ts()

        if last_ts:
            query = f"{_JOB_QUERY} after:{last_ts}"
        else:
            # First run — look back 30 days
            lookback = now_ts - (30 * 24 * 3600)
            query    = f"{_JOB_QUERY} after:{lookback}"
            logger.info("First poll — scanning last 30 days for job emails")

        logger.info(f"Gmail poll started | query prefix: {query[:100]}…")

        try:
            response = self._svc().users().messages().list(
                userId="me", q=query, maxResults=50
            ).execute()
        except HttpError as exc:
            logger.error(f"Gmail API list error: {exc}")
            return []

        messages = response.get("messages", [])
        if not messages:
            logger.info("No new job-related emails found")
            self._save_last_poll_ts(now_ts)
            return []

        logger.info(f"{len(messages)} candidate emails found — fetching full content")
        results = []

        for meta in messages:
            msg_id = meta["id"]
            try:
                raw    = self._svc().users().messages().get(userId="me", id=msg_id, format="full").execute()
                parsed = self._parse_message(raw)
                self._apply_label(msg_id, label_id)
                results.append(parsed)
            except HttpError as exc:
                logger.error(f"Failed to fetch/label message {msg_id}: {exc}")

        self._save_last_poll_ts(now_ts)
        logger.info(f"Poll complete — {len(results)} emails returned for classification")
        return results


# ── module-level helper ───────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Removes HTML tags and decodes common entities for plain-text processing."""
    text = re.sub(r"<style[^>]*>.*?</style>",   " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>",  " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>",  " ", text)
    text = re.sub(r"&nbsp;",   " ", text)
    text = re.sub(r"&amp;",    "&", text)
    text = re.sub(r"&lt;",     "<", text)
    text = re.sub(r"&gt;",     ">", text)
    text = re.sub(r"&quot;",   '"', text)
    text = re.sub(r"&#39;",    "'", text)
    text = re.sub(r"\s+",      " ", text)
    return text.strip()
