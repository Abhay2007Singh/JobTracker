# Telegram command handlers, inline-button callbacks, and message formatters.
# All handlers check the sender's chat_id against TELEGRAM_CHAT_ID before acting.

import html
from datetime import datetime, timedelta, date
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.config import config
from app.database import SessionLocal
from app.models.application import Application as JobApp, ApplicationStatus
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# In-memory state: tracks which app_id we're waiting a custom follow-up reply for
_awaiting_followup: dict[int, int] = {}  # chat_id → app_id

_FOLLOWUP_OPTIONS = [3, 5, 7, 14, 21]

_CATEGORY_LABELS: dict[str, str] = {
    "APPLICATION_CONFIRMATION": "📨 Application Confirmation",
    "INTERVIEW_INVITATION":     "🎯 Interview Invitation",
    "JOB_OFFER":                "🎉 Job Offer",
    "REJECTION":                "💔 Rejection",
    "STATUS_UPDATE":            "📋 Status Update",
}

_STATUS_LABELS: dict[str, str] = {
    "PENDING_REVIEW":       "⏳ Pending Review",
    "APPROVED":             "✅ Approved",
    "REJECTED":             "❌ Rejected (spam/irrelevant)",
    "INTERVIEWING":         "🔁 Interviewing",
    "OFFERED":              "🎉 Offered",
    "REJECTED_BY_COMPANY":  "💔 Rejected by Company",
    "GHOSTED":              "👻 Ghosted",
}

# What status to set when the user approves, based on email category
_APPROVE_STATUS: dict[str, str] = {
    "APPLICATION_CONFIRMATION": ApplicationStatus.APPROVED.value,
    "INTERVIEW_INVITATION":     ApplicationStatus.INTERVIEWING.value,
    "JOB_OFFER":                ApplicationStatus.OFFERED.value,
    "REJECTION":                ApplicationStatus.REJECTED_BY_COMPANY.value,
    "STATUS_UPDATE":            ApplicationStatus.APPROVED.value,
}


# ── auth guard ────────────────────────────────────────────────────────────────

def _authorized(update: Update) -> bool:
    """Returns True only if the message or callback came from the configured chat."""
    if update.effective_chat:
        return update.effective_chat.id == config.TELEGRAM_CHAT_ID
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message.chat.id == config.TELEGRAM_CHAT_ID
    return False


# ── command handlers ──────────────────────────────────────────────────────────

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "👋 <b>Job Tracker Bot is running!</b>\n\n"
        "I notify you whenever a job-related email arrives so you can approve or reject it.\n\n"
        "<b>Commands:</b>\n"
        "/status  — quick stats\n"
        "/pending — emails waiting for your review\n"
        "/list    — active approved applications\n"
        "/stats   — detailed breakdown\n"
        "/help    — this message",
        parse_mode="HTML",
    )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await update.message.reply_text(
        "<b>Job Tracker — Help</b>\n\n"
        "<b>When a new email arrives:</b>\n"
        "• ✅ <b>Approve</b> — confirms the application; prompts for follow-up days\n"
        "• ❌ <b>Reject</b>  — marks as spam / irrelevant\n"
        "• ⚠️ <b>Duplicate</b> — marks as a duplicate email\n"
        "• 📋 <b>View Body</b> — shows the email snippet\n\n"
        "<b>Commands:</b>\n"
        "/status  — pending, approved, interviewing counts\n"
        "/pending — list applications awaiting review\n"
        "/list    — list all approved/active applications\n"
        "/stats   — full statistics by status and platform",
        parse_mode="HTML",
    )


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        counts = {
            s.value: db.query(JobApp)
                       .filter(JobApp.status == s.value, JobApp.is_duplicate.is_(False))
                       .count()
            for s in ApplicationStatus
        }
        total      = sum(counts.values())
        rejections = counts.get("REJECTED", 0) + counts.get("REJECTED_BY_COMPANY", 0)
        text = (
            "📊 <b>Job Tracker Status</b>\n\n"
            f"📥 Pending Review  : <b>{counts.get('PENDING_REVIEW', 0)}</b>\n"
            f"✅ Approved        : <b>{counts.get('APPROVED', 0)}</b>\n"
            f"🔁 Interviewing    : <b>{counts.get('INTERVIEWING', 0)}</b>\n"
            f"🎉 Offers          : <b>{counts.get('OFFERED', 0)}</b>\n"
            f"❌ Rejections      : <b>{rejections}</b>\n"
            f"👻 Ghosted         : <b>{counts.get('GHOSTED', 0)}</b>\n\n"
            f"📌 <b>Total tracked:</b> {total}"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    finally:
        db.close()


async def handle_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        apps = (
            db.query(JobApp)
            .filter(
                JobApp.status == ApplicationStatus.PENDING_REVIEW.value,
                JobApp.is_duplicate.is_(False),
            )
            .order_by(JobApp.email_date.desc())
            .limit(10)
            .all()
        )
        if not apps:
            await update.message.reply_text("✅ No pending applications — you're all caught up!")
            return

        lines = [f"📥 <b>Pending Review ({len(apps)})</b>\n"]
        for a in apps:
            cat = _CATEGORY_LABELS.get(a.email_category or "", "📧 Email")
            lines.append(
                f"• <b>{html.escape(a.company)}</b> — {html.escape(a.role)}\n"
                f"  {cat} | {a.platform} | {a.email_date.strftime('%d/%m/%Y')}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


async def handle_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        apps = (
            db.query(JobApp)
            .filter(
                JobApp.status.in_([
                    ApplicationStatus.APPROVED.value,
                    ApplicationStatus.INTERVIEWING.value,
                    ApplicationStatus.OFFERED.value,
                ]),
                JobApp.is_duplicate.is_(False),
            )
            .order_by(JobApp.email_date.desc())
            .limit(15)
            .all()
        )
        if not apps:
            await update.message.reply_text("No active applications yet.")
            return

        lines = [f"📋 <b>Active Applications ({len(apps)})</b>\n"]
        for a in apps:
            label = _STATUS_LABELS.get(a.status, a.status)
            lines.append(
                f"• <b>{html.escape(a.company)}</b> — {html.escape(a.role)}\n"
                f"  {label} | {a.platform} | {a.email_date.strftime('%d/%m/%Y')}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        db.close()


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    db = SessionLocal()
    try:
        from sqlalchemy import func as sqlfunc
        cutoff   = datetime.utcnow() - timedelta(days=30)
        total    = db.query(JobApp).filter(JobApp.is_duplicate.is_(False)).count()
        last30   = db.query(JobApp).filter(JobApp.created_at >= cutoff, JobApp.is_duplicate.is_(False)).count()
        pending  = db.query(JobApp).filter(JobApp.status == ApplicationStatus.PENDING_REVIEW.value).count()
        interviews = db.query(JobApp).filter(JobApp.status == ApplicationStatus.INTERVIEWING.value).count()
        offers   = db.query(JobApp).filter(JobApp.status == ApplicationStatus.OFFERED.value).count()
        rejected = db.query(JobApp).filter(
            JobApp.status.in_([ApplicationStatus.REJECTED.value, ApplicationStatus.REJECTED_BY_COMPANY.value])
        ).count()

        platform_rows = (
            db.query(JobApp.platform, sqlfunc.count(JobApp.id))
            .filter(JobApp.is_duplicate.is_(False))
            .group_by(JobApp.platform)
            .order_by(sqlfunc.count(JobApp.id).desc())
            .all()
        )
        platform_lines = "\n".join(f"  • {p or 'Unknown'}: {c}" for p, c in platform_rows)

        text = (
            f"📈 <b>Job Tracker Statistics</b>\n\n"
            f"📌 Total applications : <b>{total}</b>\n"
            f"🗓 Last 30 days       : <b>{last30}</b>\n"
            f"📥 Pending review     : <b>{pending}</b>\n"
            f"🔁 Interviews         : <b>{interviews}</b>\n"
            f"🎉 Offers             : <b>{offers}</b>\n"
            f"❌ Rejections         : <b>{rejected}</b>\n\n"
            f"<b>By Platform:</b>\n{platform_lines or '  (none yet)'}"
        )
        await update.message.reply_text(text, parse_mode="HTML")
    finally:
        db.close()


# ── callback dispatcher ───────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _authorized(update):
        await query.answer("Unauthorized")
        return
    await query.answer()

    parts  = (query.data or "").split(":")
    action = parts[0]

    if   action == "approve"         and len(parts) >= 2: await _show_followup_kb(query, int(parts[1]))
    elif action == "reject"          and len(parts) >= 2: await _do_reject(query, int(parts[1]))
    elif action == "duplicate"       and len(parts) >= 2: await _do_duplicate(query, int(parts[1]))
    elif action == "details"         and len(parts) >= 2: await _show_details(query, int(parts[1]))
    elif action == "followup"        and len(parts) >= 3: await _do_approve(query, int(parts[1]), int(parts[2]))
    elif action == "followup_custom" and len(parts) >= 2: await _ask_custom_followup(query, int(parts[1]))
    elif action == "followedup"      and len(parts) >= 2: await _do_followed_up(query, int(parts[1]))
    elif action == "ghost"           and len(parts) >= 2: await _do_ghost(query, int(parts[1]))


# ── text handler (custom follow-up days) ─────────────────────────────────────

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    if chat_id not in _awaiting_followup:
        return

    try:
        days = int(update.message.text.strip())
        if not 1 <= days <= 365:
            await update.message.reply_text("Please enter a number between 1 and 365.")
            return
    except ValueError:
        await update.message.reply_text("Please enter a valid number (e.g. <b>10</b>).", parse_mode="HTML")
        return

    app_id = _awaiting_followup.pop(chat_id)
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if app:
            _apply_approval(db, app, days)
            await update.message.reply_text(
                f"✅ <b>{html.escape(app.company)}</b> — <b>{html.escape(app.role)}</b>\n"
                f"Approved with a <b>{days}-day</b> follow-up reminder.",
                parse_mode="HTML",
            )
    finally:
        db.close()


# ── action implementations ────────────────────────────────────────────────────

async def _show_followup_kb(query, app_id: int) -> None:
    row1 = [InlineKeyboardButton(f"{d}d", callback_data=f"followup:{app_id}:{d}") for d in _FOLLOWUP_OPTIONS[:3]]
    row2 = [InlineKeyboardButton(f"{d}d", callback_data=f"followup:{app_id}:{d}") for d in _FOLLOWUP_OPTIONS[3:]]
    row3 = [InlineKeyboardButton("✏️ Custom", callback_data=f"followup_custom:{app_id}")]
    await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([row1, row2, row3]))
    await query.message.reply_text(
        "⏰ <b>Set follow-up reminder:</b> how many days should I wait before reminding you?",
        parse_mode="HTML",
    )


async def _do_approve(query, app_id: int, days: int) -> None:
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if not app:
            await query.edit_message_text("❌ Application not found.")
            return
        _apply_approval(db, app, days)
        followup_str = app.followup_date.strftime("%d/%m/%Y") if app.followup_date else "—"
        await query.edit_message_text(
            format_card(app) + f"\n\n✅ <b>Approved</b> — follow-up reminder set for {followup_str}",
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _do_reject(query, app_id: int) -> None:
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if not app:
            await query.edit_message_text("❌ Application not found.")
            return
        app.status = ApplicationStatus.REJECTED.value
        db.commit()
        logger.info(f"Application {app_id} rejected by user")
        await query.edit_message_text(
            format_card(app) + "\n\n❌ <b>Marked as Rejected / Irrelevant</b>",
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _do_duplicate(query, app_id: int) -> None:
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if not app:
            await query.edit_message_text("❌ Application not found.")
            return
        app.is_duplicate = True
        db.commit()
        logger.info(f"Application {app_id} marked as duplicate by user")
        await query.edit_message_text(
            format_card(app) + "\n\n⚠️ <b>Marked as Duplicate</b>",
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _show_details(query, app_id: int) -> None:
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if not app:
            await query.answer("Application not found")
            return
        snippet = app.job_description_snippet or "(no snippet available)"
        await query.message.reply_text(
            f"📋 <b>Email — {html.escape(app.company)}</b>\n\n"
            f"<b>Subject:</b> {html.escape(app.email_subject)}\n"
            f"<b>From:</b>    {html.escape(app.email_sender)}\n"
            f"<b>Date:</b>    {app.email_date.strftime('%d/%m/%Y %H:%M')}\n\n"
            f"<b>Snippet:</b>\n{html.escape(snippet[:800])}",
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _ask_custom_followup(query, app_id: int) -> None:
    _awaiting_followup[query.message.chat.id] = app_id
    await query.message.reply_text(
        "✏️ Type the number of follow-up days (e.g. <b>10</b>):",
        parse_mode="HTML",
    )


async def _do_followed_up(query, app_id: int) -> None:
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if app:
            app.followup_sent = True
            db.commit()
    finally:
        db.close()
    await query.edit_message_text(
        (query.message.text or "") + "\n\n✅ <b>Marked as followed up.</b>",
        parse_mode="HTML",
    )


async def _do_ghost(query, app_id: int) -> None:
    db = SessionLocal()
    try:
        app = db.query(JobApp).filter(JobApp.id == app_id).first()
        if app:
            app.status       = ApplicationStatus.GHOSTED.value
            app.followup_sent = True
            db.commit()
            logger.info(f"Application {app_id} marked as GHOSTED")
    finally:
        db.close()
    await query.edit_message_text(
        (query.message.text or "") + "\n\n👻 <b>Marked as Ghosted.</b>",
        parse_mode="HTML",
    )


# ── formatting ────────────────────────────────────────────────────────────────

def format_card(app: JobApp) -> str:
    """Formats an Application ORM record as an HTML Telegram message card."""
    cat_label = _CATEGORY_LABELS.get(app.email_category or "", "📧 Email")
    conf_pct  = f"{int((app.confidence or 0) * 100)}%" if app.confidence else "—"

    lines = [
        "🔔 <b>New Job Email</b>\n",
        f"🏢 <b>Company:</b>   {html.escape(app.company)}",
        f"💼 <b>Role:</b>      {html.escape(app.role)}",
        f"🌐 <b>Platform:</b>  {app.platform}",
    ]
    if app.location:
        lines.append(f"📍 <b>Location:</b>  {html.escape(app.location)}")
    if app.salary_range:
        lines.append(f"💰 <b>Salary:</b>    {html.escape(app.salary_range)}")
    lines += [
        f"📧 <b>Type:</b>      {cat_label}",
        f"🎯 <b>Confidence:</b> {conf_pct}",
        f"📅 <b>Date:</b>      {app.email_date.strftime('%d/%m/%Y')}",
    ]
    return "\n".join(lines)


def _apply_approval(db, app: JobApp, days: int) -> None:
    """Sets status, followup_days, and followup_date when a user approves."""
    new_status      = _APPROVE_STATUS.get(app.email_category or "", ApplicationStatus.APPROVED.value)
    app.status       = new_status
    app.followup_days = days
    email_date_only  = app.email_date.date() if isinstance(app.email_date, datetime) else app.email_date
    app.followup_date = email_date_only + timedelta(days=days)
    app.followup_sent = False
    db.commit()
    logger.info(f"Application {app.id} approved → status={new_status}, followup={app.followup_date}")
