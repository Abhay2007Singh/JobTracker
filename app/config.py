# Loads and validates all environment variables used across the application.

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Gmail
    GMAIL_ADDRESS: str = os.getenv("GMAIL_ADDRESS", "")
    GMAIL_CREDENTIALS_PATH: str = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    GMAIL_TOKEN_PATH: str = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    GMAIL_LABEL: str = os.getenv("GMAIL_LABEL", "JobTracker")
    GMAIL_AUTO_MARK_READ: bool = os.getenv("GMAIL_AUTO_MARK_READ", "false").lower() == "true"

    # Gemini
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: int = int(os.getenv("TELEGRAM_CHAT_ID") or "0")

    # Google Sheets
    SHEETS_ENABLED: bool = os.getenv("SHEETS_ENABLED", "false").lower() == "true"
    SHEETS_SPREADSHEET_NAME: str = os.getenv("SHEETS_SPREADSHEET_NAME", "Job Applications Tracker")
    SHEETS_SPREADSHEET_ID: str = os.getenv("SHEETS_SPREADSHEET_ID", "")

    # App settings
    POLL_INTERVAL_MINUTES: int = int(os.getenv("POLL_INTERVAL_MINUTES", "30"))
    DEFAULT_FOLLOWUP_DAYS: int = int(os.getenv("DEFAULT_FOLLOWUP_DAYS", "7"))
    TARGET_ROLES: list = [r.strip() for r in os.getenv("TARGET_ROLES", "").split(",") if r.strip()]
    REGION: str = os.getenv("REGION", "India")
    CITY: str = os.getenv("CITY", "Bangalore")
    DATE_FORMAT: str = os.getenv("DATE_FORMAT", "%d/%m/%Y")
    SALARY_FORMAT: str = os.getenv("SALARY_FORMAT", "INR_LPA")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///jobtracker.db")

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "logs")

    def validate(self) -> None:
        missing = []
        if not self.GMAIL_ADDRESS:
            missing.append("GMAIL_ADDRESS")
        if not self.GMAIL_CREDENTIALS_PATH:
            missing.append("GMAIL_CREDENTIALS_PATH")
        if not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not self.TELEGRAM_BOT_TOKEN:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


config = Config()
