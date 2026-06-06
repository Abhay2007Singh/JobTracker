# Gmail OAuth2 authentication — handles first-run browser consent and token refresh.

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# gmail.modify  = read + label + mark-read
# spreadsheets  = read + write Google Sheets (used by sheets/sync.py)
# Both scopes are requested together so the user only authenticates once.
# NOTE: if token.json already exists with only the Gmail scope, delete it and
# re-run the app to trigger a fresh OAuth consent that includes Sheets.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _ensure_credential_files() -> None:
    """
    On cloud deployments (Railway, Render etc.) secret files cannot be committed
    to git. Instead, their JSON contents are stored as environment variables
    CREDENTIALS_JSON and TOKEN_JSON. This function writes them to disk on
    startup if the files are missing but the env vars are present.
    """
    creds_path = Path(config.GMAIL_CREDENTIALS_PATH)
    token_path = Path(config.GMAIL_TOKEN_PATH)

    if not creds_path.exists():
        creds_json = os.environ.get("CREDENTIALS_JSON", "").strip()
        if creds_json:
            creds_path.write_text(creds_json, encoding="utf-8")
            logger.info(f"credentials.json written from CREDENTIALS_JSON env var")
        else:
            logger.error("credentials.json missing and CREDENTIALS_JSON env var not set")

    if not token_path.exists():
        token_json = os.environ.get("TOKEN_JSON", "").strip()
        if token_json:
            token_path.write_text(token_json, encoding="utf-8")
            logger.info(f"token.json written from TOKEN_JSON env var")
        else:
            logger.warning("token.json missing and TOKEN_JSON env var not set — OAuth browser flow will be attempted")


def get_gmail_service():
    """
    Returns an authenticated Gmail API service object.

    First run: opens a browser window for OAuth2 consent and saves token.json.
    Subsequent runs: loads token.json and silently refreshes if expired.
    On cloud: reads credentials from CREDENTIALS_JSON / TOKEN_JSON env vars.
    """
    _ensure_credential_files()

    creds: Credentials | None = None
    token_path = Path(config.GMAIL_TOKEN_PATH)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Gmail token expired — refreshing silently")
            creds.refresh(Request())
        else:
            logger.info("No valid Gmail token found — starting OAuth2 browser flow")
            flow = InstalledAppFlow.from_client_secrets_file(
                config.GMAIL_CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Gmail token saved → {token_path}")

    return build("gmail", "v1", credentials=creds)
