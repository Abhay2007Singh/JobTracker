#!/usr/bin/env python3
# Application entry point — validates config, runs DB migrations, starts the
# Telegram bot and APScheduler, then waits until Ctrl+C.

import asyncio
import sys

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger("jobtracker")


async def main() -> None:
    # ── 1. Config validation ──────────────────────────────────────────────────
    try:
        config.validate()
    except ValueError as exc:
        logger.error(f"Configuration error: {exc}")
        sys.exit(1)
    logger.info("Configuration validated")

    # ── 2. DB migrations ──────────────────────────────────────────────────────
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_cmd
        alembic_cfg = AlembicConfig("alembic.ini")
        alembic_cmd.upgrade(alembic_cfg, "head")
        logger.info("Database schema up to date")
    except Exception as exc:
        logger.error(f"DB migration failed: {exc}")
        sys.exit(1)

    # ── 3. Telegram bot (non-blocking) ────────────────────────────────────────
    from app.telegram.bot import start_polling, stop_polling
    try:
        await start_polling()
    except Exception as exc:
        logger.error(f"Telegram bot failed to start: {exc}")
        sys.exit(1)

    # ── 4. APScheduler ────────────────────────────────────────────────────────
    from app.scheduler.jobs import setup_scheduler, poll_and_process
    scheduler = setup_scheduler()
    scheduler.start()
    logger.info(
        f"Scheduler started — Gmail poll every {config.POLL_INTERVAL_MINUTES} min | "
        f"Daily digest + follow-up check at 09:00 IST"
    )

    # ── 5. Initial Gmail poll on startup ──────────────────────────────────────
    logger.info("Running initial Gmail poll on startup…")
    await poll_and_process()

    # ── 6. Wait until Ctrl+C ─────────────────────────────────────────────────
    logger.info("JobTracker is running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()          # block until cancelled
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass

    # ── 7. Graceful shutdown ──────────────────────────────────────────────────
    logger.info("Shutting down…")
    scheduler.shutdown(wait=False)
    await stop_polling()
    logger.info("JobTracker stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
