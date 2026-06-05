# Defines the Application model — single source of truth for every tracked job application.

import enum
from datetime import datetime, date
from sqlalchemy import Integer, String, Boolean, DateTime, Date, Text, Float, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ApplicationStatus(str, enum.Enum):
    PENDING_REVIEW       = "PENDING_REVIEW"       # seen by system, awaiting user approval
    APPROVED             = "APPROVED"             # user approved via Telegram
    REJECTED             = "REJECTED"             # user marked as spam/irrelevant
    INTERVIEWING         = "INTERVIEWING"         # interview scheduled
    OFFERED              = "OFFERED"              # offer received
    REJECTED_BY_COMPANY  = "REJECTED_BY_COMPANY"  # company sent rejection
    GHOSTED              = "GHOSTED"              # no reply after follow-up window


class Platform(str, enum.Enum):
    LINKEDIN    = "LinkedIn"
    NAUKRI      = "Naukri"
    WELLFOUND   = "Wellfound"
    INTERNSHALA = "Internshala"
    INDEED      = "Indeed"
    HIRIST      = "Hirist"
    JOOBLE      = "Jooble"
    JOBSORA     = "Jobsora"
    DIRECT      = "Direct"
    REFERRAL    = "Referral"
    UNKNOWN     = "Unknown"


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Gmail message ID — prevents the same email from being processed twice
    email_id:      Mapped[str]      = mapped_column(String(255), unique=True, nullable=False, index=True)
    email_subject: Mapped[str]      = mapped_column(String(500), nullable=False)
    email_date:    Mapped[datetime] = mapped_column(DateTime,    nullable=False)
    email_sender:  Mapped[str]      = mapped_column(String(255), nullable=False)

    # Original email category from the classifier (APPLICATION_CONFIRMATION, INTERVIEW_INVITATION, etc.)
    # Separate from `status` which tracks hiring pipeline position
    email_category: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # AI confidence score from Gemini (0.0 – 1.0)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Extracted job details (filled by classifier/extractor in Part 4)
    company:                  Mapped[str]       = mapped_column(String(255),  nullable=False, default="Unknown")
    role:                     Mapped[str]       = mapped_column(String(255),  nullable=False, default="Unknown")
    platform:                 Mapped[str]       = mapped_column(String(50),   nullable=False, default=Platform.UNKNOWN.value)
    job_url:                  Mapped[str | None] = mapped_column(String(1000), nullable=True)
    job_description_snippet:  Mapped[str | None] = mapped_column(Text,         nullable=True)
    location:                 Mapped[str | None] = mapped_column(String(255),  nullable=True)
    salary_range:             Mapped[str | None] = mapped_column(String(100),  nullable=True)

    # Current status in the hiring pipeline
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ApplicationStatus.PENDING_REVIEW.value,
        index=True,
    )

    # Follow-up tracking (followup_days set by user at approval time via Telegram)
    followup_days: Mapped[int | None]  = mapped_column(Integer, nullable=True)
    followup_date: Mapped[date | None] = mapped_column(Date,    nullable=True)
    followup_sent: Mapped[bool]        = mapped_column(Boolean, nullable=False, default=False)

    # Duplicate detection
    is_duplicate:    Mapped[bool]      = mapped_column(Boolean, nullable=False, default=False)
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("applications.id"), nullable=True)

    # Google Sheets row (1-based index; null until first sync)
    sheets_row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Free-form notes added via Telegram /note command
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Application id={self.id} company={self.company!r} role={self.role!r} status={self.status}>"
