# MEXC Deposit -> Withdrawal Screenshot Workflow

Цей документ описує задачу пошуку депозиту RK-акаунта і знаходження відповідної операції у зняттях на основному MEXC, щоб зберегти screenshot деталей withdrawal.

## Що є основним MEXC

Для пошуку screenshot відкривається не AdsPower profile вибраного акаунта, а основний MEXC profile.

Основний profile береться з налаштування:

- UI: `Settings -> iCloud -> iCloud Profile ID`
- setting key: `icloud_ads_profile_id`
- код запуску: `ui/app.py::_run_find_deposit_screenshot`
- сценарій: `automation/scenarios/mexc_deposit_screenshot.py::MexcDepositScreenshotScenario`

Цей AdsPower profile має бути вже залогінений у основний MEXC. Якщо MEXC відкриває login/sign-in сторінку, сценарій зупиняється з помилкою:

`Main MEXC profile is not logged in. Log in in the iCloud AdsPower profile first.`

## Як отримуються відомості про депозити

Депозити читаються для поточного вибраного акаунта через його збережені MEXC API Key і Secret Key.

UI-кнопка:

- `Find RK Deposits`

Основний код:

- `ui/app.py::_read_latest_mexc_deposit`
- `clients/mexc_api.py::MexcApiClient.successful_deposits`

API endpoint MEXC:

- `GET /api/v3/capital/deposit/hisrec`

Запит підписується HMAC SHA256 через Secret Key. У запит додаються `recvWindow`, `timestamp` і `signature`, а API key передається в header `X-MEXC-APIKEY`.

Поточна логіка:

- читає історію депозитів максимум за 90 днів;
- MEXC history ділиться на вікна до 7 днів, бо API має обмеження по періоду;
- бере тільки успішні статуси `5` і `12`;
- сортує депозити від новіших до старіших;
- відкриває modal `RKDepositsModal`, де користувач вибирає потрібні депозити;
- найновіший депозит обраний за замовчуванням.

Після вибору дані зберігаються у папку акаунта:

- `My_Accounts/<status>/<email>/rk_deposits.json`
- legacy-сумісність для першого вибраного депозиту: `My_Accounts/<status>/<email>/rk_deposit.json`

У `rk_deposits.json` зберігаються:

- `amount`
- `coin`
- `network`
- `address`
- `tx_id`
- `insert_time`
- `status`
- `memo`
- `selected`

## Як запускається пошук screenshot

UI-кнопки:

- у modal після `Find RK Deposits`: `Find Screenshots`
- у картці акаунта: `Make Deposit Screenshot`

Перед стартом сценарій перевіряє:

- вибраний акаунт існує;
- папка акаунта існує;
- є `rk_deposits.json` або `rk_deposit.json`;
- у settings є `icloud_ads_profile_id`.

Після цього створюється `MexcDepositScreenshotScenario` з:

- `account` = вибраний RK-акаунт;
- `account_dir` = папка вибраного акаунта;
- `main_profile_id` = `icloud_ads_profile_id`;
- `adspower` = клієнт AdsPower.

## Як відбувається пошук у зняттях основного MEXC

Сценарій відкриває основний AdsPower profile через Selenium:

`open_adspower_selenium_driver(adspower, main_profile_id, context="MexcDepositScreenshotScenario")`

Потім відкриває сторінку:

`https://www.mexc.com/assets/record`

Далі сценарій працює з керованою вкладкою `assets/record`: якщо користувач
перейшов в іншу вкладку AdsPower, сценарій перемикається назад на вкладку
історії або відкриває її заново. Якщо поверх AdsPower відкрито іншу програму,
це не має ламати сценарій, бо screenshot робиться browser-level методом, а не
desktop/OS capture.

Після відкриття сторінки сценарій намагається перейти на вкладку withdrawals:

- шукає видимі елементи з текстом `withdraw` або `withdrawal`;
- клікає найменший релевантний button/link/tab;
- чекає завантаження історії.

Для кожного вибраного депозиту готується match-пакет:

- `coin_base`: базова монета без suffix після `-`;
- `date_hints`: локальні та UTC підказки з `insert_time`;
- `address_hints`: compact-підказки для обрізаних адрес у таблиці, наприклад
  `0x0cd...d928f`;
- `tx_hints`: compact-підказки для обрізаних TXID, якщо біржа показує TXID
  скорочено;
- `amount`;
- `coin`;
- `network`;
- `address`;
- `tx_id`.

Пошук у withdrawal history робиться посторінково через scoring:

- `tx_id` дає найвищий score;
- `address` також має високий score;
- якщо у депозиті є `tx_id` або `address`, кандидат має містити повний
  `tx_id`/`address` або compact hint; збіг лише за сумою, датою чи монетою
  не відкривається;
- якщо на сторінці є identity-кандидат із тією ж сумою, identity-кандидати з
  іншою сумою не відкриваються;
- `amount`, `coin`, `coin_base`, `network`, `date_hints` додають менші бали;
- рядок має пройти мінімальний score;
- на кожній сторінці сценарій перевіряє кілька кандидатів, а не тільки перший;
- якщо на поточній сторінці немає підтвердженого збігу, сценарій натискає
  `Next` у пагінації і продовжує пошук до ліміту сторінок;
- якщо рядок знайдено, сценарій знаходить details/view/more/transaction або
  сам рядок і пробує відкрити його кількома каналами: synthetic
  pointer/mouse events у DOM, Chrome DevTools `Runtime.evaluate` з
  `userGesture: true`, Selenium native click, Chrome DevTools
  `Input.dispatchMouseEvent`;
- після exact identity+amount кандидата сценарій не продовжує безцільно
  гортати сторінки, якщо details не відкрився: це фіксується як окрема
  помилка `rk_deposit_screenshot_details_open_failed.json`.

Якщо рядок не знайдено, створюється probe-файл у папці акаунта:

`rk_deposit_screenshot_probe.json`

Якщо історія не встигла завантажитись або не містить потрібних ознак, створюється:

`rk_deposit_screenshot_history_timeout.json`

## Як робиться screenshot депозиту

Після відкриття details modal/drawer сценарій шукає контейнер деталей withdrawal:

- `.ant-modal-content`
- `.ant-drawer-content`
- `[role="dialog"]`

Контейнер вважається правильним за доказовим правилом:

- якщо у депозиті є `tx_id`, у details обов'язково має бути цей `tx_id`;
- якщо `tx_id` немає, але є `address`, у details обов'язково має бути ця `address`;
- якщо немає ні `tx_id`, ні `address`, допускається тільки сильний fallback:
  `amount` + `coin/coin_base` + `network` або date hint.

Однакова сума сама по собі не є достатньою підставою для screenshot.

Screenshot зберігається у папку вибраного акаунта:

`My_Accounts/<status>/<email>/rk_deposit_<date>_<amount>_<coin>.png`

Приклад імені:

`rk_deposit_2026-08-19_143022_10_USDT.png`

Перед кожним депозитом сценарій примусово перезавантажує `assets/record` через
`driver.get(...)` і заново відкриває вкладку withdrawals, щоб новий пошук не
успадковував поточну сторінку пагінації або modal state від попередньої спроби.
У стартовий event пишеться `version`, щоб у логах було видно, яку версію
сценарію реально виконує UI-процес.

Після відкриття history встановлюється lightweight network probe для
`fetch`/`XMLHttpRequest`. Probe використовується тільки для діагностики: він
може показати, що MEXC detail endpoint спрацював, але не є джерелом screenshot
і не використовується для рендеру власного інтерфейсу.

Сценарій зберігає тільки screenshot нативного MEXC details modal/drawer через
Chrome DevTools. Automation-rendered або synthetic details-панелі заборонені:
якщо MEXC не створив свій `.ant-modal-content`, `.ant-drawer-content` або
`[role="dialog"]`, успішний screenshot не робиться.

Порядок screenshot:

1. активує потрібну вкладку на рівні Chrome target через `Page.bringToFront`;
2. якщо Chrome target мінімізований, пробує повернути window state у `normal`;
3. пробує CDP lifecycle/focus nudges (`Page.setWebLifecycleState`,
   `Emulation.setFocusEmulationEnabled`);
4. робить коротке Python-side очікування після активації target, без
   `requestAnimationFrame`, бо animation frame у фоновій вкладці може не
   виконатись до ручного перемикання користувачем;
5. робить `Page.captureScreenshot` активного viewport;
6. локально обрізає зображення по координатах видимої modal/drawer.

Якщо правильний withdrawal рядок знайдено і click по `Details` виконано, але
MEXC не домалював нативну modal/drawer у фоновому режимі, сценарій переходить у
foreground-assist режим:

- пише progress event `mexc_deposit_screenshot_foreground_required`;
- UI показує warning, що потрібно перейти в AdsPower MEXC window/tab;
- сценарій продовжує чекати появу саме нативної MEXC modal/drawer;
- коли modal/drawer з'являється, сценарій пише
  `mexc_deposit_screenshot_foreground_resumed` і автоматично робить screenshot;
- якщо користувач не відкрив вкладку до timeout, створюється
  `rk_deposit_screenshot_foreground_timeout.json`.

Details modal/drawer тримається відкритим до завершення screenshot; закриття
виконується тільки після збереження або помилки.

Full browser screenshot не зберігається як успішний результат. Якщо MEXC не
відкрив details або crop виглядає як повний viewport, сценарій завершує цей
депозит помилкою і пише probe для аналізу.

Після кожного депозиту сценарій намагається закрити details modal і перейти до наступного вибраного депозиту.

## Результат сценарію

При успіху `ScenarioResult.data` містить:

- `account_email`
- `screenshot_path`
- `screenshot_paths`
- `failures`
- `deposit_path`

UI після завершення:

- пише event `rk_deposit_screenshot_saved`;
- оновлює RK state у картці акаунта;
- показує статус `Saved X/Y RK deposit screenshot(s).`

## Важливі обмеження

- Дані депозиту беруться з MEXC API вибраного акаунта, але screenshot шукається в withdrawal history основного MEXC profile.
- Основний MEXC profile має бути залогінений вручну або попередньо.
- Якщо MEXC змінить DOM, назви вкладок або details modal, scoring може потребувати оновлення.
- Найнадійніший match: `tx_id` або `address`. Якщо їх немає у withdrawal history основного MEXC, пошук може знайти неправильний рядок або не знайти нічого.
- Screenshot не зберігається в БД, а лежить файлом у папці акаунта.
- `rk_deposits.json` є робочим файлом вибраних депозитів; його треба створити через `Find RK Deposits` перед `Make Deposit Screenshot`.
