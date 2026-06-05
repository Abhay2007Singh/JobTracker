# APScheduler job definitions — ties together polling, classification, DB persistence,
# Telegram notifications, Sheets sync, follow-up reminders, and daily digest.

import asyncio
from datetime import date, datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.exc import IntegrityError

from app.config import config
from app.database import SessionLocal
from app.models.application import Application, ApplicationStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Single poller instance — reuses the same Gmail service across poll cycles
from app.gmail.poller import GmailPoller
_poller = GmailPoller()


# ── scheduler factory ─────────────────────────────────────────────────────────

def setup_scheduler() -> AsyncIOScheduler:
    """
    Creates and configures the AsyncIOScheduler.
    Jobs run in the same asyncio event loop as the Telegram bot.
    Returns the scheduler (caller must call .start()).
    """
    scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")

    # Poll Gmail every N minutes (default 30)
    scheduler.add_job(
        poll_and_process,
        trigger=IntervalTrigger(minutes=config.POLL_INTERVAL_MINUTES),
        id="gmail_poll",
        replace_existing=True,
        misfire_grace_time=300,   # tolerate up to 5-min delay before skipping
        max_instances=1,          # never run two polls simultaneously
    )

    # Daily digest — 9:00 AM IST
    scheduler.add_job(
        daily_digest_job,
        trigger=CronTrigger(hour=9, minute=0, timezone="Asia/Kolkata"),
        id="daily_digest",
        replace_existing=True,
        max_instances=1,
    )

    # Follow-up reminder check — 9:05 AM IST (just after digest)
    scheduler.add_job(
        followup_check_job,
        trigger=CronTrigger(hour=9, minute=5, timezone="Asia/Kolkata"),
        id="followup_check",
        replace_existing=True,
        max_instances=1,
    )

    return scheduler


# ── main poll job ─────────────────────────────────────────────────────────────

async def poll_and_process() -> None:
    """
    Core job: polls Gmail, classifies each new email, saves to DB,
    sends Telegram notification, and syncs to Google Sheets.
    Sync API calls (Gmail, Gemini, Sheets) are offloaded to a thread pool
    so they never block the Telegram bot's event loop.
    """
    logger.info("Gmail poll cycle started")
    loop = asyncio.get_event_loop()

    try:
        emails = await loop.run_in_executor(None, _poller.poll)
    except Exception as exc:
        logger.error(f"Gmail poll failed: {exc}")
        return

    if not emails:
        logger.info("Poll complete — no new emails")
        return

    logger.info(f"Processing {len(emails)} candidate emails")
    db = SessionLocal()
    try:
        for email in emails:
            await _process_one_email(db, email, loop)
    finally:
        db.close()

    logger.info("Gmail poll cycle complete")


async def _process_one_email(db, email: dict, loop) -> None:
    email_id = email.get("email_id", "?")

    # ── 1. Classify + extract (sync Gemini call → thread pool) ───────────────
    try:
        from app.classifier.extractor import extract
        extracted = await loop.run_in_executor(None, extract, email)
    except Exception as exc:
        logger.error(f"[{email_id}] Extraction error: {exc}")
        return

    if extracted is None:
        return  # IRRELEVANT or failed — already logged by extractor

    # ── 2. Duplicate check ────────────────────────────────────────────────────
    try:
        from app.deduplication.detector import check_duplicate
        dup = await loop.run_in_executor(None, check_duplicate, db, extracted)
    except Exception as exc:
        logger.error(f"[{email_id}] Duplicate check error: {exc}")
        return

    # ── 3. Persist to DB ──────────────────────────────────────────────────────
    app = _save_application(db, extracted, dup)
    if app is None:
        return

    # ── 4. Telegram notification ──────────────────────────────────────────────
    try:
        from app.telegram.bot import notify_new_application, notify_duplicate
        if dup.is_duplicate:
            await notify_duplicate(app, dup.details)
        else:
            await notify_new_application(app)
    except Exception as exc:
        logger.error(f"[{email_id}] Telegram notification error: {exc}")

    # ── 5. Google Sheets sync (sync → thread pool) ────────────────────────────
    if config.SHEETS_ENABLED:
        try:
            from app.sheets.sync import get_sheets_sync
            sync = get_sheets_sync()
            await loop.run_in_executor(None, sync.sync_application, db, app)
        except Exception as exc:
            logger.error(f"[{email_id}] Sheets sync error: {exc}")


def _save_application(db, extracted, dup) -> Optional[Application]:
    """Saves an ExtractedData + DuplicateResult to the DB. Returns the saved ORM object."""
    try:
        app = Application(
            email_id                 = extracted.email_id,
            email_subject            = extracted.email_subject,
            email_date               = extracted.email_date,
            email_sender             = extracted.email_sender,
            email_category           = extracted.category,
            confidence               = extracted.confidence,
            company                  = extracted.company,
            role                     = extracted.role,
            platform                 = extracted.platform,
            job_url                  = extracted.job_url,
            location                 = extracted.location,
            salary_range             = extracted.salary_range,
            job_description_snippet  = extracted.job_description_snippet,
            status                   = ApplicationStatus.PENDING_REVIEW.value,
            is_duplicate             = dup.is_duplicate,
            duplicate_of_id          = dup.duplicate_of_id,
        )
        db.add(app)
        db.commit()
        db.refresh(app)
        logger.info(f"Saved application id={app.id}: {app.company!r} — {app.role!r}")
        return app
    except IntegrityError:
        db.rollback()
        logger.info(f"[{extracted.email_id}] Already in DB — skipping (race condition)")
        return None
    except Exception as exc:
        db.rollback()
        logger.error(f"[{extracted.email_id}] DB save failed: {exc}")
        return None


# ── follow-up reminder job ────────────────────────────────────────────────────

async def followup_check_job() -> None:
    """
    Runs at 9:05 AM IST daily.
    Finds approved applications whose follow-up date has passed,
    sends a Telegram reminder, and marks followup_sent=True.
    Also auto-syncs updated rows to Google Sheets.
    """
    logger.info("Follow-up check job started")
    db  = SessionLocal()
    loop = asyncio.get_event_loop()
    try:
        today = date.today()
        apps  = (
            db.query(Application)
            .filter(
                Application.followup_date  <= today,
                Application.followup_sent.is_(False),
                Application.status         == ApplicationStatus.APPROVED.value,
            )
            .all()
        )

        sent = 0
        for app in apps:
            try:
                from app.telegram.bot import send_followup_reminder
                await send_followup_reminder(app)
                app.followup_sent = True
                sent += 1
            except Exception as exc:
                logger.error(f"Follow-up reminder failed for id={app.id}: {exc}")

        db.commit()

        if config.SHEETS_ENABLED and sent:
            from app.sheets.sync import get_sheets_sync
            sync = get_sheets_sync()
            for app in apps:
                try:
                    await loop.run_in_executor(None, sync.sync_application, db, app)
                except Exception as exc:
                    logger.error(f"Sheets sync after follow-up failed for id={app.id}: {exc}")

        logger.info(f"Follow-up check complete — {sent} reminder(s) sent")
    finally:
        db.close()


# ── daily digest job ──────────────────────────────────────────────────────────

async def daily_digest_job() -> None:
    """
    Runs at 9:00 AM IST daily.
    Sends a morning summary of the tracker state to Telegram.
    """
    logger.info("Daily digest job started")
    db = SessionLocal()
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        counts = {
            s.value: db.query(Application)
                       .filter(Application.status == s.value, Application.is_duplicate.is_(False))
                       .count()
            for s in ApplicationStatus
        }

        stats = {
            "pending":      counts.get("PENDING_REVIEW", 0),
            "approved":     counts.get("APPROVED", 0),
            "interviewing": counts.get("INTERVIEWING", 0),
            "offered":      counts.get("OFFERED", 0),
            "rejections":   counts.get("REJECTED", 0) + counts.get("REJECTED_BY_COMPANY", 0),
            "ghosted":      counts.get("GHOSTED", 0),
            "total":        sum(counts.values()),
            "new_today":    db.query(Application)
                              .filter(
                                  Application.created_at  >= today_start,
                                  Application.is_duplicate.is_(False),
                              )
                              .count(),
        }

        from app.telegram.bot import send_daily_digest
        await send_daily_digest(stats)
        logger.info("Daily digest sent")
    finally:
        db.close()
