# Gmail OAuth2 authentication — handles first-run browser consent and token refresh.

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


def get_gmail_service():
    """
    Returns an authenticated Gmail API service object.

    First run: opens a browser window for OAuth2 consent and saves token.json.
    Subsequent runs: loads token.json and silently refreshes if expired.
    """
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
