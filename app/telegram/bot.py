# Telegram bot — singleton setup, command/callback registration, and
# outbound notification functions called by the scheduler.

import html as _html
from datetime import date

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application as TelegramApp,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import config
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

_app: TelegramApp | None = None


def get_app() -> TelegramApp:
    """Returns the singleton PTB Application, creating it on first call."""
    global _app
    if _app is None:
        # Lazy import of handlers to avoid any circular import at module level
        from app.telegram.handlers import (
            handle_callback,
            handle_help,
            handle_list,
            handle_pending,
            handle_start,
            handle_stats,
            handle_status,
            handle_text_input,
        )

        _app = TelegramApp.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        _app.add_handler(CommandHandler("start",   handle_start))
        _app.add_handler(CommandHandler("status",  handle_status))
        _app.add_handler(CommandHandler("pending", handle_pending))
        _app.add_handler(CommandHandler("list",    handle_list))
        _app.add_handler(CommandHandler("stats",   handle_stats))
        _app.add_handler(CommandHandler("help",    handle_help))
        _app.add_handler(CallbackQueryHandler(handle_callback))
        # Text handler last — catches custom follow-up day input
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input))

        logger.info("Telegram bot application configured")
    return _app


async def start_polling() -> None:
    """Initialises the bot and starts long-polling for updates."""
    app = get_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot polling started")


async def stop_polling() -> None:
    """Gracefully stops the bot."""
    app = get_app()
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    logger.info("Telegram bot stopped")


# ── outbound notifications (called by the scheduler) ─────────────────────────

async def notify_new_application(job_app) -> None:
    """
    Sends a new-application card to the configured Telegram chat.
    job_app is a saved Application ORM instance (status=PENDING_REVIEW).
    """
    from app.telegram.handlers import format_card

    text     = format_card(job_app)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve",      callback_data=f"approve:{job_app.id}"),
            InlineKeyboardButton("❌ Reject",        callback_data=f"reject:{job_app.id}"),
        ],
        [
            InlineKeyboardButton("⚠️ Duplicate",    callback_data=f"duplicate:{job_app.id}"),
            InlineKeyboardButton("📋 View Body",    callback_data=f"details:{job_app.id}"),
        ],
    ])
    await get_app().bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info(f"Notification sent for application id={job_app.id} ({job_app.company})")


async def notify_duplicate(job_app, duplicate_details: str) -> None:
    """Sends a lower-priority duplicate-detection notice."""
    text = (
        f"⚠️ <b>Possible Duplicate Detected</b>\n\n"
        f"🏢 <b>Company:</b> {_html.escape(job_app.company)}\n"
        f"💼 <b>Role:</b>    {_html.escape(job_app.role)}\n"
        f"🌐 <b>Platform:</b> {job_app.platform}\n\n"
        f"<i>{_html.escape(duplicate_details)}</i>"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ It's New",      callback_data=f"approve:{job_app.id}"),
        InlineKeyboardButton("⚠️ Confirm Dup",  callback_data=f"duplicate:{job_app.id}"),
    ]])
    await get_app().bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def send_followup_reminder(job_app) -> None:
    """Sends a follow-up reminder when an application hasn't had a reply."""
    days = job_app.followup_days or config.DEFAULT_FOLLOWUP_DAYS
    text = (
        f"⏰ <b>Follow-up Reminder</b>\n\n"
        f"No response from <b>{_html.escape(job_app.company)}</b> in <b>{days} days</b>.\n"
        f"Role: {_html.escape(job_app.role)}\n"
        f"Applied: {job_app.email_date.strftime('%d/%m/%Y')}\n\n"
        f"<i>Consider sending a follow-up email.</i>"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Followed Up",   callback_data=f"followedup:{job_app.id}"),
        InlineKeyboardButton("👻 Mark Ghosted",  callback_data=f"ghost:{job_app.id}"),
    ]])
    await get_app().bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    logger.info(f"Follow-up reminder sent for application id={job_app.id}")


async def send_daily_digest(stats: dict) -> None:
    """Sends a morning summary of the tracker state."""
    today = date.today().strftime("%d/%m/%Y")
    text = (
        f"☀️ <b>Daily Job Tracker Digest — {today}</b>\n\n"
        f"📥 Pending review  : <b>{stats.get('pending', 0)}</b>\n"
        f"✅ Approved        : <b>{stats.get('approved', 0)}</b>\n"
        f"🔁 Interviewing    : <b>{stats.get('interviewing', 0)}</b>\n"
        f"🎉 Offers          : <b>{stats.get('offered', 0)}</b>\n"
        f"❌ Rejections      : <b>{stats.get('rejections', 0)}</b>\n"
        f"👻 Ghosted         : <b>{stats.get('ghosted', 0)}</b>\n\n"
        f"📊 <b>Total tracked:</b> {stats.get('total', 0)}\n"
        f"🆕 <b>New today:</b>     {stats.get('new_today', 0)}"
    )
    await get_app().bot.send_message(
        chat_id=config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode="HTML",
    )
