# MEXC 2FA Link Review

Дата: 2026-07-29

## Статус

Задача виконана: сценарій створення/прив'язки MEXC Google Authenticator працює коректно для вибраного акаунта.

Сценарій запускається з картки акаунта кнопкою `Create 2FA/Link 2FA` біля 2FA-блоку. Основний код сценарію знаходиться в `automation/scenarios/link_mexc_2fa.py`.

## Як працює сценарій

1. Перевіряє, що вибраний акаунт має AdsPower profile, збережений MEXC password і доступні mailbox credentials.
2. Якщо в акаунті вже є `two_fa_secret`, UI просить підтвердити перезапис.
3. Відкриває AdsPower browser і переходить на `https://www.mexc.com/user/security/manage-google-auth`.
4. Якщо MEXC викинув з акаунта, сценарій пробує автоматично залогінитися через збережений password.
5. Натискає перший `Next`, переходить до кроку з QR/key.
6. Зчитує 2FA secret key зі сторінки, перевіряє його через `pyotp.TOTP`, одразу зберігає в акаунт і оновлює 2FA widget у застосунку.
7. Натискає другий `Next`, відкриває email security verification modal.
8. Натискає `Get Code`, після цього шукає тільки свіжий email code через `MexcEmailCodeFetcher`.
9. Якщо код не прийшов за 180 секунд, UI питає користувача: чекати ще 180 секунд чи завершити процес.
10. Вводить email code у modal і натискає modal `Submit`.
11. Чекає, поки email modal закриється і з'явиться inline поле `Authenticator Code`.
12. Генерує актуальний 2FA code через `pyotp` з уже збереженого secret.
13. Вводить 2FA code в inline поле `Authenticator Code`.
14. Натискає inline `Submit`, прив'язаний до форми з цим полем.
15. Перевіряє успішне завершення і повертає `two_fa_secret` у результаті сценарію.

## Важливі технічні рішення

- Email-коди не парсяться напряму в сценарії. Використовується спільний сервіс `services/mexc_email_service.py`.
- 2FA secret зберігається до відкриття email verification modal, бо після modal key може бути вже недоступний для копіювання.
- Для email `Submit` кнопка шукається тільки всередині видимої `Security Verification` modal, щоб не натиснути `Next` на сторінці позаду.
- Для фінального 2FA `Submit` сценарій одразу використовує inline submit path, якщо бачить inline поле `Authenticator Code`.
- Для кнопок `type="submit"` використовується `form.requestSubmit(button)` як fallback до звичайного click.

## Логування

Сценарій детально логує кожен етап:

- `2fa_secret_found`;
- `2fa_secret_early_save_done`;
- `2fa_get_code_active_check`;
- `2fa_email_code_wait_start`;
- `2fa_email_code_found`;
- `2fa_security_modal_button_click`;
- `2fa_totp_step_detected`;
- `2fa_totp_input_filled`;
- `2fa_submit_path_selected`;
- `2fa_inline_submit_click`;
- `2fa_success`.

На failure зберігаються artifacts у `logs/mexc_registration/<timestamp>_<email_hash>/`: screenshot, HTML, text dump і JSON probes. Email маскується, password/2FA/email code не логуються відкритим текстом.

## Поточні слабкі місця

- Сценарій залежить від DOM MEXC і класів/текстів Ant Design форм.
- Auto-login зроблений best-effort: якщо MEXC змінить login flow або додасть додаткову перевірку, може знадобитися окремий fallback.
- CAPTCHA проходиться вручну через існуючу captcha notification/modal логіку.
- Успіх перевіряється за текстом/URL, тому при зміні success-екрана MEXC може знадобитися уточнення success detector.

## Підсумок

MEXC 2FA linking сценарій робочий. Найважливіші edge cases вже враховані: раннє збереження secret, довге очікування email code з рішенням користувача, modal email submit і inline final 2FA submit.
