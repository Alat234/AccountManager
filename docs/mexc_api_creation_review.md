# MEXC API Creation Review

Дата: 2026-07-30

## Статус

Реалізовано сценарій автоматичного створення MEXC API key для вибраного акаунта з desktop-застосунку.

Сценарій запускається з картки акаунта кнопкою `Create API` біля полів `API Key` / `Secret Key`. Після успішного створення ключі автоматично записуються в desktop app.

## Що зроблено

- Додано сценарій `CreateMexcApiScenario` у `automation/scenarios/create_mexc_api.py`.
- Додано спільні browser/login/security helpers у `automation/scenarios/mexc_browser_helpers.py`.
- Додано кнопку `Create API` у `ui/details_tab.py`.
- Додано запуск сценарію, перевірки акаунта і збереження результату в `ui/app.py`.
- Розширено debug-redaction у `automation/scenarios/mexc_debug.py`, щоб API/secret не світилися у failure artifacts.
- Додано перевірку referral input у `automation/scenarios/register_mexc.py`: після вводу код читається назад з DOM і підтверджується логом `referral_value_verified`.

## Як працює API-сценарій

1. Перевіряє, що акаунт має AdsPower profile, MEXC password, mailbox credentials і `two_fa_secret`.
2. Якщо 2FA ще немає, UI пропонує створити 2FA і після успіху автоматично продовжує API-сценарій.
3. Відкриває `https://www.mexc.com/user/openapi`.
4. Якщо MEXC не залогінений, пробує автоматичний login через збережений password і 2FA; captcha лишається ручним кроком.
5. Чекає завантаження API-форми.
6. Виставляє тільки потрібні permissions:
   - Spot: `View Account Details`, `Edit Account Info`, `View Order Details`, `Trade`;
   - Futures: `View Account Details`, `View Order Details`.
7. Інші permissions, включно з withdraw/transfer/P2P/futures order placing, не вибираються.
8. `Notes` заповнюється як `trading`.
9. IP address лишається порожнім.
10. Ставиться risk agreement checkbox і натискається `Create`.
11. У security modal натискається `Get Code`, очікується email code через існуючий `MexcEmailCodeFetcher`.
12. Email code вводиться першим; тільки після цього генерується і вводиться свіжий 2FA code.
13. Якщо 2FA code застарів/не прийнявся, сценарій пробує новий code.
14. Після успішної перевірки сценарій витягує `Access Key` і `Secret Key` з фінальної MEXC modal.
15. Ключі записуються в desktop app, після цього на MEXC натискається `Confirm`.

## Важливі технічні рішення

- Permissions виставляються по `input.value`, а не по тексту label. Це стабільніше, бо MEXC має однакові назви `View Account Details` у Spot/Futures.
- Чекбокси клікаються послідовно і потім перевіряються фінальним станом: `missing` / `unwanted`.
- Security inputs шукаються спочатку по точних id: `emailCode`, `googleAuthCode`.
- Email code і 2FA code вводяться в правильному порядку, щоб TOTP не протухав під час очікування пошти.
- Extractor ключів читає фінальну modal `Created successfully`, де MEXC показує `Access Key`, а не `API Key`.
- Debug logs не пишуть відкрито password, 2FA secret, email code, API key або secret key.

## Логи для перевірки

Основні маркери успішного API-сценарію:

- `api_create_start`
- `api_form_wait_done`
- `api_permissions_set_done`
- `api_note_filled`
- `api_security_verification_done`
- `api_key_extract_done`
- `api_confirm_copied_done`
- `api_create_success`

Для referral-перевірки:

- `referral_value_verified` означає, що referral code реально залишився в input після вводу.
- `referral_value_verify_failed` означає, що поле не зберегло очікуване значення.

## Поточні слабкі місця

- MEXC DOM часто змінюється, тому сценарій залежить від актуальної верстки Ant Design/MEXC.
- CAPTCHA залишається ручним кроком.
- Якщо MEXC після `Continue` лишає кнопку у loading або не відкриває verification step, сценарій падає з artifacts для аналізу.
- API без IP діє 90 днів, але IP навмисно лишається порожнім за вимогою.

## Підсумок

Основний API flow реалізований: login check, 2FA precondition, точні permissions, email verification, fresh 2FA, extraction API/secret, запис у desktop app і confirm на MEXC.

Окремо додано доказову перевірку referral code через `referral_value_verified`, щоб у логах було видно не просто факт вводу, а факт прийняття значення полем.
