# Job Application Tracking System

A lightweight, fully local AI-powered tracker that monitors your Gmail for job-related emails, classifies them with Gemini, and lets you approve or reject each application directly from Telegram. All data stays on your machine — SQLite database, no cloud, no Docker, no Redis.

---

## How It Works

```
Gmail inbox
    ↓  (every 30 min)
Rule-based filter   →  obvious noise dropped instantly (no API call)
    ↓
Gemini AI           →  classifies email type + extracts company/role/platform/salary
    ↓
Duplicate detector  →  exact email ID + fuzzy company+role matching
    ↓
SQLite DB           →  saved as PENDING_REVIEW
    ↓
Telegram Bot        →  you tap ✅ Approve / ❌ Reject / ⚠️ Duplicate
    ↓
Google Sheets       →  row written/updated automatically
    ↓
Follow-up reminder  →  Telegram alert after N days of silence
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Tested on 3.14.5 |
| Google Cloud Project | With Gmail API + Sheets API enabled |
| OAuth 2.0 credentials | `client_secret_*.json` downloaded (Desktop App type) |
| Gemini API key | From [aistudio.google.com](https://aistudio.google.com) — free tier |
| Telegram Bot Token | From [@BotFather](https://t.me/BotFather) |
| Telegram Chat ID | Your personal user ID |

---

## One-Time Setup

### 1. Create a virtual environment

```bash
cd jobtracker
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Verify your .env file

Your `.env` is already pre-filled from the setup interview. Open it and confirm:

```
GMAIL_ADDRESS=abhaykumar2007singh@gmail.com
GMAIL_CREDENTIALS_PATH=C:/Users/Abhay/Documents/project/application_automation/client_secret_...json
GEMINI_API_KEY=AQ.A...
TELEGRAM_BOT_TOKEN=871...:AAFbN...
TELEGRAM_CHAT_ID=6....
SHEETS_ENABLED=true
SHEETS_SPREADSHEET_NAME=Job Applications Tracker
```

> ⚠️ **Never commit `.env` to git.** It is already in `.gitignore`.

---

## Running the App

```bash
cd jobtracker
python run.py
```

### What happens on first run

1. **DB migrations** apply automatically (`alembic upgrade head`)
2. **Gmail OAuth** — a browser window opens. Sign in with `abhaykumar2007singh@gmail.com` and grant both **Gmail** and **Google Sheets** permissions. A `token.json` is saved — this is your auth token for all future runs.
3. **Initial Gmail poll** — scans the last 30 days for job-related emails
4. **Google Sheets** — creates the "Job Applications Tracker" spreadsheet and saves its ID to `.env` automatically
5. **Telegram bot** starts receiving your commands

> **Note:** If `token.json` already exists from a previous Gmail-only run, delete it and re-run to get a fresh token with both Gmail + Sheets scopes.

To stop the app at any time: **Ctrl+C**

---

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Welcome message + command list |
| `/status` | Quick count — pending, approved, interviewing, offers, rejections |
| `/pending` | List emails waiting for your review (up to 10) |
| `/list` | Active approved/interviewing/offered applications (up to 15) |
| `/stats` | Full breakdown by status + platform |
| `/help` | Help message |

### When a new email arrives

The bot sends you a card like this:

```
🔔 New Job Email

🏢 Company:    Google
💼 Role:       SDE Intern
🌐 Platform:   LinkedIn
📍 Location:   Bangalore
💰 Salary:     12-15 LPA
📧 Type:       Application Confirmation
🎯 Confidence: 87%
📅 Date:       05/06/2026

[✅ Approve]  [❌ Reject]
[⚠️ Duplicate] [📋 View Body]
```

- **✅ Approve** — prompts for follow-up reminder days (3 / 5 / 7 / 14 / 21 / Custom), then marks the application as active
- **❌ Reject** — marks as spam/irrelevant
- **⚠️ Duplicate** — marks as a duplicate email
- **📋 View Body** — shows the email snippet and metadata

### Follow-up reminder

When your follow-up date passes, the bot sends:

```
⏰ Follow-up Reminder

No response from Google in 7 days.
Role: SDE Intern
Applied: 29/05/2026

[✅ Followed Up]  [👻 Mark Ghosted]
```

---

## Project Structure

```
jobtracker/
├── run.py                      ← entry point (python run.py)
├── .env                        ← your secrets (never commit)
├── .env.example                ← template
├── .gitignore
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       ├── 0001_initial_schema.py
│       └── 0002_add_email_category_confidence.py
├── app/
│   ├── config.py               ← loads all env vars
│   ├── database.py             ← SQLAlchemy engine + session
│   ├── models/
│   │   └── application.py      ← Application ORM model
│   ├── gmail/
│   │   ├── auth.py             ← OAuth2 flow + token refresh
│   │   └── poller.py           ← Gmail inbox polling
│   ├── classifier/
│   │   ├── types.py            ← ExtractedData dataclass + EmailCategory enum
│   │   ├── rules.py            ← fast rule-based pre-filter
│   │   ├── gemini.py           ← Gemini AI classifier + extractor
│   │   ├── extractor.py        ← pipeline orchestrator
│   │   └── validator.py        ← normalises extracted data
│   ├── deduplication/
│   │   └── detector.py         ← exact + fuzzy duplicate detection
│   ├── telegram/
│   │   ├── bot.py              ← PTB setup + outbound notifications
│   │   └── handlers.py         ← command + callback handlers
│   ├── sheets/
│   │   └── sync.py             ← Google Sheets create/write/update
│   ├── scheduler/
│   │   └── jobs.py             ← APScheduler jobs
│   └── utils/
│       └── logger.py           ← rotating file + console logs
└── logs/
    └── jobtracker.log          ← auto-created on first run
```

---

## Google Sheets Layout

The sheet is created automatically. Columns A–M:

| ID | Company | Role | Platform | Status | Email Type | Location | Salary Range | Applied Date | Follow-up Date | Job URL | Notes | Confidence % |

---

## Scheduled Jobs

| Job | When | What |
|---|---|---|
| Gmail poll | Every 30 minutes | Scans inbox, classifies, notifies |
| Daily digest | 9:00 AM IST | Sends morning stats to Telegram |
| Follow-up check | 9:05 AM IST | Sends overdue follow-up reminders |

---

## Troubleshooting

**Browser doesn't open for Gmail auth on first run**
Run this in the jobtracker folder to trigger auth manually:
```bash
python -c "from app.gmail.auth import get_gmail_service; get_gmail_service()"
```

**`token.json` errors / permission denied on Sheets**
Delete `token.json` and re-run. You'll be asked to re-authorize with both Gmail + Sheets scopes.

**Gemini rate limit errors**
The classifier retries automatically (5s → 10s → 20s). If you're consistently hitting limits, the free tier allows 1,500 requests/day — more than enough for personal tracking.

**`SHEETS_SPREADSHEET_ID` is empty after first run**
Check `logs/jobtracker.log` — the sheet URL is logged there. Copy the ID from the URL and add it to `.env` manually:
```
SHEETS_SPREADSHEET_ID=your_sheet_id_here
```

**Database errors**
Re-run migrations manually:
```bash
alembic upgrade head
```

---

## Security Notes

- `.env`, `token.json`, `client_secret_*.json`, and `*.db` are all in `.gitignore`
- No secrets are hardcoded anywhere in the codebase
- The Telegram bot only responds to your personal `TELEGRAM_CHAT_ID`
- All data stays on your local machine — SQLite database, local logs

---

## Free Tier Limits

| Service | Free Limit | Expected Usage |
|---|---|---|
| Gmail API | 1 billion units/day | ~100 units per poll |
| Gemini API | 1,500 req/day, 15 req/min | ~10–50 emails/day |
| Sheets API | 300 req/min | 1 req per approved application |
| Telegram Bot API | Unlimited for personal bots | — |
