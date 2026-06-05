# Google Sheets sync — creates the "Job Applications Tracker" spreadsheet on first run,
# then writes or updates one row per application whenever its data changes.
# Uses the same OAuth token.json as Gmail (both scopes requested in auth.py).

import re
from pathlib import Path
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_SHEET_TAB   = "Applications"
_HEADER_ROW  = [
    "ID", "Company", "Role", "Platform", "Status", "Email Type",
    "Location", "Salary Range", "Applied Date", "Follow-up Date",
    "Job URL", "Notes", "Confidence %", "Mail Link",
]
# Number of columns — used to build range strings like "Applications!A2:N2"
_LAST_COL = "N"
_NUM_COLS  = len(_HEADER_ROW)


class SheetsSync:
    """
    Manages a single Google Sheet that mirrors the applications database.

    Lifecycle:
      1. First run with SHEETS_SPREADSHEET_ID empty → creates the sheet,
         writes headers, saves the ID back to .env automatically.
      2. Subsequent runs → uses the stored ID.

    Each Application row is keyed by sheets_row_index stored in the DB so
    updates always hit the correct row regardless of reordering in the sheet.
    """

    def __init__(self) -> None:
        self._service        = None
        self._spreadsheet_id = config.SHEETS_SPREADSHEET_ID or None

    # ── service ───────────────────────────────────────────────────────────────

    def _svc(self):
        if self._service is None:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from app.gmail.auth import SCOPES

            token_path = Path(config.GMAIL_TOKEN_PATH)

            if not token_path.exists():
                # No token yet — run the full Gmail OAuth flow first
                from app.gmail.auth import get_gmail_service
                get_gmail_service()

            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                token_path.write_text(creds.to_json(), encoding="utf-8")

            self._service = build("sheets", "v4", credentials=creds)
        return self._service

    # ── spreadsheet bootstrap ─────────────────────────────────────────────────

    def get_or_create_spreadsheet(self) -> str:
        """Returns the spreadsheet ID, creating the sheet on first call."""
        if self._spreadsheet_id:
            return self._spreadsheet_id

        logger.info(f"Creating new Google Sheet: '{config.SHEETS_SPREADSHEET_NAME}'")
        result = self._svc().spreadsheets().create(
            body={
                "properties": {"title": config.SHEETS_SPREADSHEET_NAME},
                "sheets":     [{"properties": {"title": _SHEET_TAB}}],
            }
        ).execute()

        self._spreadsheet_id = result["spreadsheetId"]
        sheet_url = f"https://docs.google.com/spreadsheets/d/{self._spreadsheet_id}"

        # Persist the ID into .env so future runs reuse the same sheet
        try:
            from dotenv import set_key
            set_key(str(Path(".env").resolve()), "SHEETS_SPREADSHEET_ID", self._spreadsheet_id)
            logger.info(f"SHEETS_SPREADSHEET_ID saved to .env")
        except Exception as exc:
            logger.warning(f"Could not auto-save sheet ID to .env: {exc}")
            logger.info(f"ACTION REQUIRED — add this to your .env:\n  SHEETS_SPREADSHEET_ID={self._spreadsheet_id}")

        logger.info(f"Sheet created: {sheet_url}")

        self._write_headers(self._spreadsheet_id)
        self._format_header_row(self._spreadsheet_id)

        return self._spreadsheet_id

    def _write_headers(self, spreadsheet_id: str) -> None:
        """Writes the header row if the sheet is empty."""
        existing = (
            self._svc().spreadsheets().values()
            .get(spreadsheetId=spreadsheet_id, range=f"{_SHEET_TAB}!A1:{_LAST_COL}1")
            .execute()
            .get("values")
        )
        if existing:
            logger.info("Sheet already has a header row — skipping header write")
            return

        self._svc().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{_SHEET_TAB}!A1",
            valueInputOption="RAW",
            body={"values": [_HEADER_ROW]},
        ).execute()
        logger.info("Header row written to sheet")

    def _format_header_row(self, spreadsheet_id: str) -> None:
        """Makes the header row bold and freezes it."""
        # Get the sheet ID (numeric) for batchUpdate
        sheet_meta = (
            self._svc().spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties")
            .execute()
        )
        sheet_id = sheet_meta["sheets"][0]["properties"]["sheetId"]

        self._svc().spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    # Bold header
                    {
                        "repeatCell": {
                            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                            "cell":  {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold",
                        }
                    },
                    # Freeze header row
                    {
                        "updateSheetProperties": {
                            "properties": {
                                "sheetId": sheet_id,
                                "gridProperties": {"frozenRowCount": 1},
                            },
                            "fields": "gridProperties.frozenRowCount",
                        }
                    },
                ]
            },
        ).execute()

    # ── row sync ──────────────────────────────────────────────────────────────

    def sync_application(self, db_session, app) -> None:
        """
        Writes or updates the sheet row for the given Application ORM record.
        - If app.sheets_row_index is None  → appends a new row and saves the index.
        - If app.sheets_row_index is set   → overwrites that row in place.
        Does nothing if SHEETS_ENABLED is False.
        """
        if not config.SHEETS_ENABLED:
            return

        spreadsheet_id = self.get_or_create_spreadsheet()
        row_values     = _app_to_row(app)

        try:
            if app.sheets_row_index:
                self._update_row(spreadsheet_id, app.sheets_row_index, row_values)
            else:
                row_index = self._append_row(spreadsheet_id, row_values)
                if row_index:
                    app.sheets_row_index = row_index
                    db_session.commit()
                    logger.info(f"Application {app.id} synced to sheet row {row_index}")
        except HttpError as exc:
            logger.error(f"Sheets API error syncing application {app.id}: {exc}")

    def _append_row(self, spreadsheet_id: str, values: list) -> Optional[int]:
        result = (
            self._svc().spreadsheets().values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=f"{_SHEET_TAB}!A:{_LAST_COL}",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [values]},
            )
            .execute()
        )
        updated_range = result.get("updates", {}).get("updatedRange", "")
        return _parse_row_index(updated_range)

    def _update_row(self, spreadsheet_id: str, row_index: int, values: list) -> None:
        range_ = f"{_SHEET_TAB}!A{row_index}:{_LAST_COL}{row_index}"
        self._svc().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_,
            valueInputOption="USER_ENTERED",
            body={"values": [values]},
        ).execute()

    def sync_all(self, db_session) -> None:
        """
        Syncs every non-duplicate application to the sheet.
        Useful for an initial bulk load or a repair run.
        """
        from app.models.application import Application as JobApp
        apps = db_session.query(JobApp).filter(JobApp.is_duplicate.is_(False)).all()
        logger.info(f"Bulk sync: {len(apps)} applications → Google Sheets")
        for app in apps:
            self.sync_application(db_session, app)


# ── module-level singleton ────────────────────────────────────────────────────

_sheets_sync: Optional[SheetsSync] = None


def get_sheets_sync() -> SheetsSync:
    """Returns the module-level SheetsSync singleton."""
    global _sheets_sync
    if _sheets_sync is None:
        _sheets_sync = SheetsSync()
    return _sheets_sync


# ── helpers ───────────────────────────────────────────────────────────────────

def _app_to_row(app) -> list:
    """Converts an Application ORM record to a flat list of sheet cell values."""
    mail_link = (
        f'=HYPERLINK("https://mail.google.com/mail/u/0/#all/{app.email_id}","Open Email")'
        if app.email_id else ""
    )
    return [
        app.id,
        app.company,
        app.role,
        app.platform,
        app.status,
        app.email_category or "",
        app.location        or "",
        app.salary_range    or "",
        app.email_date.strftime("%d/%m/%Y")    if app.email_date    else "",
        app.followup_date.strftime("%d/%m/%Y") if app.followup_date else "",
        app.job_url  or "",
        app.notes    or "",
        f"{int((app.confidence or 0) * 100)}%",
        mail_link,
    ]


def _parse_row_index(updated_range: str) -> Optional[int]:
    """Extracts the row number from a Sheets range string like 'Applications!A5:M5'."""
    match = re.search(r"!A(\d+)", updated_range)
    return int(match.group(1)) if match else None
