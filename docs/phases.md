# AccountsManager — Roadmap & Phases

## Current State (after Phase 1 + Phase 2)

### What's done

**Phase 1 — Core Refactor + AdsPower Integration**
- Modular architecture: `models/`, `storage/`, `services/`, `clients/`, `ui/`, `automation/`, `bot/`
- `AdsPowerClient` — HTTP wrapper for AdsPower Local API (profiles, browsers, groups)
- `Account` model extended: `ads_profile_id`, `ads_serial_number`
- `AutomationTask` model for tracking scenario execution
- DB auto-migration via PRAGMA table_info
- `sync_with_adspower()` — syncs AdsPower profiles to local DB on startup
- UI: settings tab with AdsPower API key, TG bot token/user ID fields
- UI: "AdsPower" button launches browser profile for selected account
- Deleted legacy files (`core.py`, `modals.py`, `ui_widgets.py`, `test_2fa.py`, `clients/dolphin.py`)

**Phase 2 — Automation Framework**
- `BaseScenario` (ABC) — template: start browser → run → stop browser (via AdsPower debuggerAddress)
- `ScenarioRunner` — ThreadPoolExecutor (max_workers=2), submit/track/callback
- `CaptchaService` — observer pattern, listeners notified when captcha detected
- `TaskService` — task lifecycle: create → start → complete/fail, stored in SQLite
- `captcha.py` — CSS selector-based detection + polling until captcha disappears
- First scenario: `OpenMexcScenario` — opens MEXC in AdsPower browser, takes screenshot
- UI wired: "Open MEXC" button, captcha notification in status bar, `on_complete` callback, shutdown on close

### Project structure

```
AccountsManager/
├── main.py                          # Entry point
├── models/
│   ├── account.py                   # Account dataclass
│   ├── mailbox.py                   # Mailbox dataclass
│   └── task.py                      # AutomationTask dataclass
├── storage/
│   ├── constants.py                 # BASE_DIR, STATUSES, colors
│   ├── database.py                  # SQLite CRUD + auto-migration
│   ├── file_manager.py              # Account folders, info.txt
│   └── settings.py                  # JSON key-value settings
├── services/
│   ├── account_service.py           # Account CRUD + AdsPower sync
│   ├── mailbox_service.py           # Mailbox CRUD
│   ├── task_service.py              # Task lifecycle
│   └── captcha_service.py           # Captcha notification relay
├── clients/
│   └── adspower.py                  # AdsPower Local API client
├── automation/
│   ├── base.py                      # BaseScenario + ScenarioResult
│   ├── runner.py                    # ScenarioRunner (ThreadPoolExecutor)
│   ├── captcha.py                   # CSS-based captcha detection
│   └── scenarios/
│       └── open_mexc.py             # OpenMexcScenario
├── bot/                             # Empty (Phase 3)
│   ├── __init__.py
│   └── handlers/
│       └── __init__.py
├── ui/
│   ├── app.py                       # Main window, wires everything
│   ├── account_list.py              # Left sidebar
│   ├── details_tab.py               # Account fields, finances, 2FA
│   ├── notes_tab.py                 # Text notes
│   ├── table_tab.py                 # Spreadsheet view
│   ├── settings_tab.py              # Settings (AdsPower, TG)
│   ├── modals.py                    # Delete, batch upload
│   └── widgets.py                   # Entry-with-copy, 2FA widget
├── docs/
│   ├── architecture.md              # Full architecture doc
│   ├── adspower_api_reference.md    # AdsPower API reference
│   └── phases.md                    # This file
└── My_Accounts/                     # Data dir (folders per status)
```

### Database tables
- `accounts` — email, password, api_key, secret_key, two_fa_secret, old_email, status, text_notes, invested, deposit, balance, net_profit, ads_profile_id, ads_serial_number
- `mailboxes` — email, password, server
- `automation_tasks` — id, account_email, scenario_type, status, created_at, completed_at, result_message, result_data

### Settings (settings.json)
- `adspower_api_key`
- `telegram_bot_token`
- `telegram_user_id`

### Dependencies
- `customtkinter` — UI
- `requests` — AdsPower API
- `selenium` — browser automation
- `pyotp` — 2FA codes

---

## Phase 3 — Telegram Bot (aiogram 3)

**Goal**: remote status checking + automation launch from Telegram.

### Tasks

1. **`bot/bot.py`** — aiogram 3 Dispatcher, run in daemon thread with own asyncio loop
   - On startup: register handlers, start polling
   - Thread-safe: services accessed from bot thread via run_coroutine_threadsafe or direct calls (DB opens own connections)
   - Daemon thread → dies when desktop app closes

2. **`bot/middlewares.py`** — Auth middleware
   - Whitelist by `telegram_user_id` from settings
   - Reject all messages from unauthorized users

3. **`bot/handlers/accounts.py`** — Account info
   - `/accounts` — list all accounts (email + status + balance)
   - `/info <email>` — detailed account info

4. **`bot/handlers/status.py`** — Quick lookups
   - `/status` — summary (total accounts, total balance, active tasks)
   - `/2fa <email>` — generate TOTP code for account
   - `/code <email>` — fetch latest email verification code

5. **`bot/handlers/automation.py`** — Remote automation control
   - `/run <scenario> <email>` — submit scenario to ScenarioRunner
   - `/tasks` — list recent tasks + statuses
   - `/sync` — trigger AdsPower sync

6. **`bot/handlers/captcha.py`** — Captcha notifications
   - Register CaptchaService listener → send TG message when captcha detected
   - User gets alerted: "CAPTCHA on account X — go to browser window"

7. **`bot/keyboards.py`** — Inline keyboards
   - Account selection, scenario selection

8. **Wire into `ui/app.py`**
   - Start bot thread in `__init__` (if token + user_id configured)
   - Pass services to bot

### Dependencies to add
- `aiogram>=3.0`

---

## Phase 4 — Full MEXC Automation Scenarios

**Goal**: Selenium scenarios for real MEXC operations.

### Scenarios to build

1. **`automation/scenarios/login.py`** — `LoginScenario`
   - Navigate to MEXC login
   - Fill email + password
   - Handle CAPTCHA (detect → notify → poll)
   - Handle 2FA if enabled (pyotp)
   - Verify login success

2. **`automation/scenarios/balance.py`** — `BalanceScenario`
   - Login (reuse LoginScenario or check if already logged in)
   - Navigate to assets page
   - Scrape balance values
   - Update Account.balance in DB
   - Return screenshot

3. **`automation/scenarios/kyc.py`** — `KycLinkScenario`
   - Login
   - Navigate to KYC page
   - Extract KYC link/status
   - Return link + screenshot

4. **`automation/scenarios/register.py`** — `RegisterScenario`
   - Create iCloud hidden email (via icloud client)
   - Create AdsPower profile (via AdsPowerClient)
   - Open browser → navigate to MEXC registration
   - Fill email → CAPTCHA → email verification code (auto-fetch via mailbox)
   - Set password → complete registration
   - Save new account to DB

### Supporting work

5. **`clients/icloud.py`** — iCloud Hide My Email client
   - Generate hidden email address
   - List existing hidden emails
   - Library: `icloud-hme` or `hidemyemail-generator` (needs research)

6. **CAPTCHA selector tuning** — test against real MEXC pages, update `CAPTCHA_SELECTORS` in `automation/captcha.py`

7. **Email code auto-fetch** — `email_parser.py` already exists, wire into scenarios

---

## Phase 5 — Polish & Extras

- Task history tab in UI
- Scenario scheduling (run balance check every N hours)
- Export accounts to CSV/Excel
- Bulk scenario execution (run on all accounts)
- Better error handling + retry logic in scenarios
- Logging setup (file + console)

---

## Architecture Rules

1. **UI and Bot never call each other** — both call Services
2. **Services are the only DB accessor** — no direct DB calls from UI/Bot
3. **Each DB method opens/closes own connection** — thread-safe by design
4. **AdsPower is source of truth** for browser profiles — app syncs from it
5. **Scenarios are self-contained** — BaseScenario handles browser lifecycle
6. **CAPTCHA = Pause+Notify+Poll** — user solves manually in browser, automation polls until gone
7. **Bot runs as daemon thread** — easy to extract to VPS later (just run bot/bot.py separately)

## CAPTCHA Approach

MEXC uses interactive captchas (slider, puzzle, image selection). Cannot be solved programmatically.

Flow:
1. Scenario detects captcha via CSS selectors (`automation/captcha.py`)
2. `CaptchaService.notify()` alerts all listeners (UI status bar, TG message)
3. User switches to open AdsPower browser window, solves captcha manually
4. Scenario polls browser every 2s until captcha element disappears
5. If solved → continue. If timeout (120s) → scenario fails.
