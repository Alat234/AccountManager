# MEXC Referral Registration Review

Дата: 2026-07-28

## Статус

Задача виконана: реєстрація MEXC акаунта через referral code для вже створеного AdsPower-профілю доведена до робочого сценарію.

Реалізація не ідеальна: referral code блок/slider відкривається довго. Поточний код спочатку пробує звичайні Selenium/JS clicks, а коли MEXC/React не відкриває блок, використовує fallback через DOM reveal. Через це етап referral code займає помітно більше часу, ніж треба.

## Очікуваний сценарій

1. Відкрити AdsPower профіль вибраного акаунта.
2. Перейти на сторінку реєстрації MEXC.
3. Ввести email акаунта.
4. Ввести referral code з налаштувань застосунку.
5. Пройти CAPTCHA вручну, якщо вона з'явиться.
6. Перейти до email verification step або натиснути `Get Code`, якщо кнопка активна.
7. Прочитати актуальний email-код з пошти відповідного акаунта.
8. Ввести 6-значний verification code.
9. Ввести default password з налаштувань застосунку.
10. Пройти фінальну CAPTCHA, якщо вона з'явиться.
11. Завершити реєстрацію.
12. Якщо акаунт створився, записати використаний пароль у поле password акаунта.

## Що реалізовано

### Налаштування MEXC

Додано MEXC-секцію в `ui/settings_tab.py`.

Реалізовано:

- поле `Referral Code`;
- поле `Default Password`;
- збереження в `settings.json` через ключі:
  - `mexc_referral_code`;
  - `mexc_default_password`;
- валідацію default password перед збереженням.

### Валідація пароля

Додано `utils/validators.py`.

`PasswordValidator` перевіряє:

- мінімум 10 символів;
- хоча б одну велику літеру;
- хоча б одну малу літеру;
- хоча б одну цифру;
- хоча б один спецсимвол;
- тільки ASCII-символи.

### Email-коди MEXC

Оновлено `email_parser.py` і `services/mexc_email_service.py`.

Реалізовано:

- IMAP folder discovery через `mail.list()`;
- логування доступних і перевірених папок;
- перевірку `inbox`, Gmail spam/junk/trash/all mail та інших spam/junk папок з IMAP flags;
- ліміт перевірки 25 останніх листів на папку;
- фільтр `not_before_ts`, щоб не брати старі коди з попередніх спроб;
- ignored codes list, щоб при retry не використовувати вже відхилений код;
- polling коду протягом 180 секунд;
- пошук коду для конкретного email акаунта.

### Automation scenario

Оновлено:

- `automation/scenarios/register_mexc.py`;
- `automation/scenarios/mexc_selectors.py`;
- `automation/scenarios/mexc_debug.py`;
- `automation/captcha.py`.

Сценарій зараз робить:

1. старт AdsPower browser через існуючий `BaseScenario`;
2. відкриття `https://www.mexc.com/register`;
3. пошук і введення email;
4. відкриття/referral code fallback reveal;
5. введення referral code;
6. натискання `Continue`;
7. CAPTCHA detection, desktop notification і очікування ручного проходження;
8. розпізнавання email verification step;
9. натискання `Get Code`, якщо кнопка активна;
10. очікування актуального email-коду;
11. введення коду у 6 окремих OTP input boxes;
12. retry, якщо MEXC відхилив старий/невалідний код;
13. перехід на password step;
14. введення default password;
15. натискання final submit/confirm;
16. повернення використаного пароля у `ScenarioResult.data`.

### Debug і логування

Додано детальне логування кожного важливого етапу:

- page loaded;
- email filled;
- referral expand/reveal attempts;
- referral filled;
- continue clicked;
- captcha detected/not detected/solved;
- email folders checked;
- code found/not found;
- OTP accepted/retried;
- password filled;
- submit clicked.

На failure зберігаються artifacts у `logs/mexc_registration/<timestamp>_<email_hash>/`:

- `metadata.json`;
- `page_probe_failure.json`;
- `page_failure.html`;
- `screenshot_failure.png`;
- CAPTCHA/referral probes, якщо вони були зібрані.

Email у логах маскується. Password, referral code і verification code не логуються відкритим текстом.

### CAPTCHA

Оновлено `automation/captcha.py`.

Реалізовано:

- GeeTest selectors;
- reCAPTCHA/Google iframe checks;
- фільтр active CAPTCHA, щоб не зависати на залишкових `captcha`/`geetest` DOM-елементах після успішного проходження;
- desktop modal/notification через існуючий `CaptchaService`.

## Що протестовано

Перевірено syntax-only compile:

```powershell
python -m py_compile automation\scenarios\register_mexc.py automation\scenarios\mexc_selectors.py automation\captcha.py email_parser.py services\mexc_email_service.py
```

Під час live-тестів через застосунок підтверджено:

- AdsPower профіль відкривається.
- Сторінка MEXC registration відкривається.
- Email вводиться.
- Referral code вводиться через fallback reveal.
- CAPTCHA визначається, користувач проходить її вручну, сценарій продовжує роботу.
- Email verification step визначається.
- `Get Code` натискається, якщо активний.
- Email-код шукається через IMAP.
- Старі коди відсікаються через `not_before_ts`/ignored codes.
- 6-значний код вводиться в OTP-поля.
- Password step відкривається.
- Default password вводиться.

## Що не ідеально

### 1. Referral code slider відкривається повільно

Поточний стан:

- звичайні Selenium/JS clicks по label/span/svg часто не відкривають MEXC referral slider;
- input є в DOM, але контейнер має hidden class типу `_inviteCodeInputHide_...`;
- сценарій після кількох спроб використовує fallback DOM reveal і тільки тоді вводить referral code;
- через це етап referral code помітно довгий.

Що бажано покращити пізніше:

1. Знайти точний React event target або state, який відкриває slider без DOM reveal.
2. Скоротити кількість невдалих click strategies перед fallback.
3. Або зробити DOM reveal першим fallback після 1-2 швидких спроб, щоб не чекати довго.

### 2. End-to-end треба ще прогнати на кількох акаунтах

Один flow доведено до робочого стану, але MEXC може змінювати DOM/CAPTCHA/email behavior. Варто протестувати ще кілька різних акаунтів і поштових скриньок.

## Поточний висновок

MEXC referral registration сценарій робочий і задача вважається виконаною.

Основний technical debt: повільне відкриття referral code блоку. Це не блокує реєстрацію, але погіршує швидкість і стабільність сценарію.
