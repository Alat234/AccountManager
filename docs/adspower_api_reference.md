# AdsPower Local API Reference

## Connection
- Base URL: currently `http://local.adspower.net:50401/`; older AdsPower setups may use `http://local.adspower.net:50325/`.
- Auth: Bearer token in header (when security enabled)
- Response format: `{"code": 0, "data": {...}, "msg": "success"}`

## Rate Limits
| Profile Count | Limit |
|---|---|
| 0-200 | 2 req/sec |
| 200-5000 | 5 req/sec |
| >5000 | 10 req/sec |

Profile/proxy ops: 1 req/sec always.

## Core Endpoints

### Browser Operations
| Endpoint | Method | Key Params |
|---|---|---|
| `/api/v1/browser/start` | GET | user_id, serial_number, headless, launch_args |
| `/api/v1/browser/stop` | GET | user_id |
| `/api/v1/browser/active` | GET | user_id |

`/browser/start` response returns:
- `ws.selenium` — debugger address for Selenium
- `ws.puppeteer` — WebSocket URL for Playwright
- `webdriver` — path to chromedriver.exe
- `debug_port`

### Profile Management
| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/user/create` | POST | Create profile (requires group_id, fingerprint_config) |
| `/api/v1/user/update` | POST | Update profile |
| `/api/v1/user/list` | GET | List/search profiles (page, page_size, group_id, user_id) |
| `/api/v1/user/delete` | POST | Delete profiles (batch up to 100) |
| `/api/v1/user/regroup` | POST | Move profiles between groups |

### Group Management
| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/group/create` | POST | Create group (group_name) |
| `/api/v1/group/list` | GET | List groups (group_name, page, page_size) |

### Proxy Management (V2)
| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/proxy-list/create` | POST | Add proxies (max 500) |
| `/api/v2/proxy-list/list` | POST | Query proxies |

## Selenium Integration Pattern
```python
resp = requests.get(f"{BASE}/api/v1/browser/start?user_id={profile_id}").json()
chrome_options = Options()
chrome_options.add_experimental_option("debuggerAddress", resp["data"]["ws"]["selenium"])
driver = webdriver.Chrome(resp["data"]["webdriver"], options=chrome_options)
```

## Playwright Integration Pattern
```python
resp = httpx.get(f"{BASE}/api/v1/browser/start?user_id={profile_id}").json()
browser = await playwright.chromium.connect_over_cdp(resp["data"]["ws"]["puppeteer"])
```

## Python Libraries
1. **`adspower`** (CrocoFactory) — pip install adspower[selenium] — OOP, context managers, sync+async
2. **`adspower-sdk`** (liweilijie) — pip install adspower-sdk — multi-process with Redis lease

## Docs
- Official: https://localapi-doc-en.adspower.com/
- GitHub samples: https://github.com/AdsPower/localAPI
- CrocoFactory lib: https://github.com/CrocoFactory/adspower
