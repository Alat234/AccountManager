# AccountsManager — Architecture

## Overview

Desktop CRM for MEXC crypto accounts. Two interfaces: CustomTkinter desktop app + Telegram bot.
AdsPower anti-detect browser for automation. Selenium for browser scenarios.

## Architecture Layers

```
┌─────────────────────────────────────────────────┐
│              Interfaces (parallel)              │
│  ┌──────────────┐       ┌────────────────────┐  │
│  │  Desktop UI  │       │   Telegram Bot     │  │
│  │  (CTk sync)  │       │  (aiogram async)   │  │
│  └──────┬───────┘       └────────┬───────────┘  │
│         └──────────┬─────────────┘              │
│                    ▼                            │
│         ┌──────────────────┐                    │
│         │     Services     │                    │
│         └────────┬─────────┘                    │
│         ┌────────┴────────┐                     │
│         ▼                 ▼                     │
│  ┌─────────────┐  ┌──────────────┐              │
│  │   Storage   │  │   Clients    │              │
│  └─────────────┘  └──────┬───────┘              │
│                          ▼                      │
│                  ┌───────────────┐               │
│                  │  Automation   │               │
│                  └───────────────┘               │
│                    Models                       │
└─────────────────────────────────────────────────┘
```

**Rule**: UI and Bot never call each other. Both call Services only.

## Module Map

### models/
| File | Contents |
|---|---|
| `account.py` | `Account` dataclass — email, password, API keys, 2FA, finances, `ads_profile_id`, `ads_serial_number` |
| `mailbox.py` | `Mailbox` dataclass — IMAP credentials |
| `task.py` | `AutomationTask` dataclass — id, scenario_type, status, result |

### storage/
| File | Responsibility |
|---|---|
| `constants.py` | `BASE_DIR`, `STATUSES`, status labels/colors |
| `database.py` | `DatabaseManager` — SQLite CRUD for accounts, mailboxes, tasks. Auto-migrates schema |
| `file_manager.py` | `FileManager` — account folders, info.txt, move/rename/delete on disk |
| `settings.py` | `SettingsManager` — JSON key-value (adspower_api_key, telegram_bot_token, telegram_user_id) |

### services/
| File | Responsibility |
|---|---|
| `account_service.py` | Account CRUD + `sync_with_adspower()` — syncs AdsPower profiles to local DB |
| `mailbox_service.py` | Mailbox CRUD |
| `task_service.py` | Automation task lifecycle (create/update/query) |
| `captcha_service.py` | CAPTCHA relay: automation → UI/TG → automation (threading.Event) |

### clients/
| File | Responsibility |
|---|---|
| `adspower.py` | `AdsPowerClient` — HTTP wrapper for AdsPower Local API. Browser start/stop, profile CRUD, groups |
| `icloud.py` | iCloud Hide My Email — generate hidden email addresses |

### automation/
| File | Responsibility |
|---|---|
| `base.py` | `BaseScenario` (ABC) + `ScenarioResult`. Template: start browser → run → stop browser |
| `runner.py` | `ScenarioRunner` — ThreadPoolExecutor, submit scenarios, track results |
| `captcha.py` | CAPTCHA detection helpers for Selenium |
| `scenarios/login.py` | MEXC login scenario |
| `scenarios/balance.py` | Balance check + screenshot |
| `scenarios/kyc.py` | KYC link generation |
| `scenarios/register.py` | Full MEXC registration (iCloud email → register → CAPTCHA → verify) |

### bot/
| File | Responsibility |
|---|---|
| `bot.py` | aiogram 3 setup, dispatcher. Runs in daemon thread with own asyncio loop |
| `middlewares.py` | Auth middleware — whitelist by telegram_user_id |
| `handlers/accounts.py` | `/accounts`, `/info <email>` |
| `handlers/status.py` | `/status`, `/2fa`, `/code` |
| `handlers/automation.py` | `/run`, `/tasks`, `/open`, `/close`, `/create`, `/sync` |
| `handlers/captcha.py` | Receive CAPTCHA image, relay user answer |
| `keyboards.py` | Inline keyboards for account selection, scenarios |

### ui/
| File | Responsibility |
|---|---|
| `app.py` | Main window. Wires services, syncs AdsPower on startup |
| `account_list.py` | Left sidebar — search, filter, account list |
| `details_tab.py` | Account fields, finances, 2FA widget, email codes widget |
| `notes_tab.py` | Text notes editor |
| `table_tab.py` | Spreadsheet view (Treeview) |
| `settings_tab.py` | AdsPower API key, Telegram bot token/user ID, mailbox management |
| `modals.py` | Delete confirmation, batch upload, CAPTCHA modal |
| `widgets.py` | Entry-with-copy, TwoFactorAuthWidget, EmailCodesWidget, CaptchaWidget |

## Database Schema

### accounts
| Column | Type | Notes |
|---|---|---|
| email | TEXT UNIQUE | Primary identifier |
| password, api_key, secret_key, two_fa_secret | TEXT | Credentials |
| old_email | TEXT | Previous email |
| status | TEXT | "Живі акаунти" / "Забанені ф'ючі" / "Дроп загубився" |
| text_notes | TEXT | Free-form notes |
| invested, deposit, balance, net_profit | REAL | Finances |
| ads_profile_id | TEXT | AdsPower profile ID |
| ads_serial_number | INTEGER | AdsPower serial number |

### mailboxes
| Column | Type |
|---|---|
| email | TEXT UNIQUE |
| password | TEXT |
| server | TEXT |

### automation_tasks
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | UUID |
| account_email | TEXT FK | → accounts.email |
| scenario_type | TEXT | "login", "balance", "kyc", "register" |
| status | TEXT | "pending", "running", "completed", "failed" |
| created_at, completed_at | TEXT | ISO datetime |
| result_message, result_data | TEXT | Outcome |

## Key Flows

### AdsPower Sync
App startup → `AdsPowerClient.list_all_profiles()` → compare with local DB →
create new accounts for unknown profiles, mark orphans for missing ones.

### CAPTCHA Relay
Scenario hits CAPTCHA → screenshot → `CaptchaService.request_solve()` →
notifies UI (CaptchaModal) + TG (send photo) → user answers →
`CaptchaService.submit_answer()` → scenario thread wakes up, continues.

### Account Registration
Create iCloud hidden email → Create AdsPower profile →
Run RegisterScenario (Selenium) → CAPTCHA relay → Email code auto-fetch → Done.

### Bot ↔ Desktop Coexistence
Bot runs in daemon thread (own asyncio loop). Dies when UI closes.
Both call the same Services. Thread-safe: each DB method opens/closes own connection.

## Settings (settings.json)
- `adspower_api_key` — AdsPower Local API authentication
- `telegram_bot_token` — aiogram bot token
- `telegram_user_id` — authorized Telegram user ID
