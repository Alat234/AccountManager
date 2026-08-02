# Automation Scenarios Guide

Дата: 2026-08-02

Цей документ описує, як у проекті створювати нові автоматичні сценарії так, щоб вони підтримували:

- checkpoints і продовження з уже досягнутого етапу;
- ручне перехоплення керування через UI;
- роботу при поганому інтернеті;
- CAPTCHA як ручний етап;
- негайну зупинку при закритті AdsPower-вкладки;
- короткі користувацькі повідомлення та звукові сповіщення;
- детальні технічні логи тільки у `logs/`.

Документ треба використовувати як базовий стандарт для реєстрації, 2FA, API та майбутніх сценаріїв.

## Основна Архітектура

Автоматизація складається з кількох шарів:

1. `BaseScenario` запускає браузер, виконує сценарій і закриває/зупиняє ресурси.
2. Конкретний сценарій описує бізнес-логіку: реєстрація, 2FA, API тощо.
3. `CheckpointRunner` керує етапами сценарію, аналізує поточний екран і вирішує, чи виконувати крок, пропустити його, чекати, питати користувача або зупинятись.
4. `PageStateAnalyzer` визначає, на якому екрані зараз браузер.
5. UI підключає `manual_assist_handler`, `network_recovery_handler`, `progress_reporter` і показує користувачу тільки короткі етапи.
6. `TaskService` і `OperationEventService` створюють історію задач, події, toast-сповіщення і звук.

## Головні Файли

| Файл | Призначення |
| --- | --- |
| `automation/base.py` | Базовий клас сценарію, старт/стоп AdsPower, cancel, перевірка закритої вкладки |
| `automation/checkpoints.py` | Універсальний checkpoint-runner |
| `automation/recovery.py` | Manual assist, типи дій користувача, класифікація помилок |
| `automation/progress.py` | Перетворення debug-step-ів у короткі повідомлення для UI |
| `automation/scenarios/mexc_state.py` | Аналізатор станів MEXC-сторінок |
| `automation/scenarios/mexc_browser_helpers.py` | Спільні MEXC helper-и: login, CAPTCHA, email code, TOTP, inputs |
| `automation/scenarios/register_mexc.py` | Приклад checkpoint-сценарію реєстрації |
| `automation/scenarios/link_mexc_2fa.py` | Приклад checkpoint-сценарію 2FA |
| `automation/scenarios/create_mexc_api.py` | Приклад checkpoint-сценарію API |
| `automation/scenarios/mexc_debug.py` | Технічні debug-логи, screenshots, page probes, redaction секретів |
| `services/task_service.py` | Створення/оновлення задач, `task_completed`, `task_failed`, `task_waiting_user` |
| `services/operation_event_service.py` | Події для журналу операцій і toast-сповіщень |
| `services/mexc_email_service.py` | Очікування MEXC email-коду з cancel/checker підтримкою |
| `ui/app.py` | Запуск сценаріїв, manual assist dialog, network dialog, notifications |

## Базовий Клас Сценарію

Кожен сценарій має наслідувати `BaseScenario`.

Основні поля і методи:

| API | Для чого |
| --- | --- |
| `run() -> ScenarioResult` | Основна логіка конкретного сценарію |
| `execute() -> ScenarioResult` | Загальна обгортка: старт браузера, `run`, обробка помилки, stop browser |
| `self.driver` | Selenium driver AdsPower-профілю |
| `self.account` | Поточний акаунт |
| `self.progress_reporter` | Callback для короткого прогресу |
| `self.manual_assist_handler` | Callback UI для ручного керування |
| `self.network_recovery_handler` | Callback UI для поганого інтернету |
| `self.cancel_event` | `threading.Event`, який зупиняє сценарій |
| `cancel()` | Скасувати сценарій і закрити AdsPower browser |
| `_raise_if_cancelled()` | Кинути помилку, якщо користувач скасував сценарій |
| `browser_is_closed()` | Перевірити, чи AdsPower-вкладка/сесія закрита |
| `_raise_if_browser_closed()` | Негайно зупинити сценарій, якщо вкладку закрито |

Обов'язкове правило: у довгих циклах сценарій має регулярно викликати:

```python
self._raise_if_cancelled()
self._raise_if_browser_closed()
```

Це потрібно для очікування email-коду, CAPTCHA, завантаження сторінки, пошуку input-ів і витягування результату.

## Результат Сценарію

Сценарій повертає `ScenarioResult`:

```python
return ScenarioResult(
    success=True,
    message="MEXC API key created for account@example.com",
    data={
        "account_email": self.account.email,
        "api_key": api_key,
        "secret_key": secret_key,
    },
)
```

Правила:

- `message` має бути коротким і зрозумілим для користувача.
- Секрети можна передавати у `data`, якщо вони потрібні для збереження в app.
- Debug-логи мають редагувати секрети через `MexcRegistrationDebug.with_secrets(...)`.
- Не показувати stacktrace користувачу. Stacktrace і probes мають бути тільки в `logs/`.

## CheckpointRunner

`CheckpointRunner` живе в `automation/checkpoints.py`.

Він вирішує:

- чи поточний екран уже відповідає наступному кроку;
- чи попередній крок уже зроблено і його треба пропустити;
- чи сторінка ще вантажиться;
- чи є network error;
- чи відкрита не та вкладка;
- чи потрібна CAPTCHA;
- чи треба manual assist;
- чи сценарій уже дійшов до terminal state.

Створення runner-а:

```python
runner = CheckpointRunner(
    driver_getter=lambda: self.driver,
    analyzer=self.state_analyzer,
    debug=self.debug,
    manual_assist_handler=self.manual_assist_handler,
    network_recovery_handler=self.network_recovery_handler,
    captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha"),
    default_terminal_states={"register_completed"},
)
runner.run(self._scenario_checkpoints())
```

Для сценаріїв, де terminal state ще не означає повне завершення, не треба ставити `default_terminal_states`.

Наприклад API:

- `api_created` означає, що ключі вже показані на екрані;
- але сценарій ще має витягнути `api_key` і `secret_key`;
- тому `api_created` використовується як `done_state`, а не як terminal state.

## ScenarioCheckpoint

Кожен checkpoint описує один логічний етап.

Поля:

| Поле | Призначення |
| --- | --- |
| `name` | Стабільна назва кроку для логів, progress і resume |
| `action` | Метод, який виконує крок |
| `allowed_states` | Стани екрана, з яких цей крок можна виконувати |
| `done_states` | Стани, які означають, що крок уже виконано |
| `terminal_states` | Стани, які означають, що весь сценарій уже завершено |
| `recover_wrong_tab` | Метод, який повертає браузер на правильну сторінку |
| `wait_timeout` | Скільки чекати, поки unknown/loading стане відомим станом |
| `min_confidence` | Мінімальна впевненість analyzer-а |
| `action_already_handles_captcha` | Якщо `action` сам обробляє CAPTCHA |

Приклад:

```python
ScenarioCheckpoint(
    name="security_verification",
    action=self._complete_security_verification,
    allowed_states={"security_modal_email", "security_modal_totp"},
    done_states={"api_created"},
    recover_wrong_tab=self._open_api_page,
)
```

## Як Проектувати Checkpoints

Кожен сценарій треба розділяти на маленькі етапи.

Добрий checkpoint:

- має одну відповідальність;
- може бути безпечно повторений або пропущений;
- має чіткі `allowed_states`;
- має чіткі `done_states`;
- після ручного втручання може зрозуміти, чи треба продовжити з цього кроку або наступного.

Поганий checkpoint:

- робить одразу 5-7 різних дій;
- не може визначити, чи він уже виконаний;
- залежить тільки від sleep;
- не перевіряє, чи вкладка закрита;
- не має зрозумілого state в analyzer-і.

## Page State Analyzer

Analyzer має відповідати на питання: "Що зараз на екрані?"

Для MEXC використовується `MexcPageStateAnalyzer` у `automation/scenarios/mexc_state.py`.

Поточні ключові стани:

| State | Значення |
| --- | --- |
| `browser_closed` | Selenium/AdsPower вкладка закрита або session invalid |
| `wrong_browser_tab` | Відкрита не MEXC вкладка, але можна знайти релевантну |
| `network_loading` | Сторінка ще вантажиться |
| `network_error` | Видима помилка мережі або reload/error page |
| `captcha` | Видима CAPTCHA |
| `login` | MEXC login/sign-in |
| `register_email` | Форма вводу email для реєстрації |
| `register_code` | Етап email verification code при реєстрації |
| `register_password` | Етап password при реєстрації |
| `register_completed` | Акаунт уже створений/користувач у MEXC |
| `twofa_intro` | Початковий екран Google Authenticator setup |
| `twofa_secret` | Екран із secret key / QR |
| `twofa_completed` | 2FA уже ввімкнено |
| `api_form` | Форма створення API key |
| `api_created` | Modal/екран із Access Key і Secret Key |
| `security_modal_email` | Security verification, потрібен email code |
| `security_modal_totp` | Security verification, потрібен Google Authenticator/TOTP |

Коли додається новий сценарій, треба:

1. Додати нові DOM-сигнали в JS snapshot analyzer-а.
2. Додати state у `_pick_state`.
3. Поставити правильний пріоритет.
4. Додати URL/tab markers, якщо сценарій має окрему сторінку.
5. Перевірити, що новий state не перебивається загальнішим state-ом.

Наприклад API states мають бути вище за `register_completed`, бо сторінка API теж може мати загальні account-сигнали.

## Робота З Вкладками

Analyzer має вміти не тільки читати DOM, але і переконатись, що активна правильна вкладка.

Для MEXC це робить `_ensure_relevant_mexc_tab(...)`:

- якщо поточна вкладка MEXC, вона використовується;
- якщо поточна не MEXC, analyzer шукає серед `driver.window_handles`;
- пріоритет: security tab, openapi tab, register tab, будь-яка MEXC tab;
- якщо знайдено правильну вкладку, driver переключається на неї;
- якщо вкладку не знайдено, повертається `wrong_browser_tab`.

У checkpoint-ах треба додавати:

```python
recover_wrong_tab=self._open_target_page
```

Тоді сценарій сам відкриє правильну сторінку, якщо активна не та вкладка.

## Manual Assist

Manual assist потрібен, коли analyzer не знає, що робити з поточним екраном.

Використовується:

- `ManualAssistAction.CONTINUE`
- `ManualAssistAction.RESTART`
- `ManualAssistAction.CANCEL`
- `ManualAssistAction.TIMEOUT`
- `ManualAssistResult`
- `ManualAssistController`

UI handler знаходиться в `ui/app.py`:

```python
scenario.manual_assist_handler = lambda step, states, initial: self._manual_assist_for_scenario(
    scenario,
    step,
    states,
    initial,
)
```

Поведінка:

- відкривається dialog "Manual control is needed";
- користувач може працювати руками у AdsPower;
- сценарій спостерігає до 10 хвилин;
- якщо dialog закрити, сценарій не скасовується, а продовжує спостерігати;
- кнопка `Continue` активується, коли analyzer бачить дозволений state;
- при `Cancel` сценарій зупиняється;
- при timeout сценарій падає зі зрозумілою помилкою.

Правило: manual assist не має бути першим варіантом. Перед ним runner має:

1. почекати known state;
2. спробувати network recovery;
3. обробити CAPTCHA;
4. переключитись/відкрити правильну вкладку;
5. тільки потім просити ручну допомогу.

## Network Recovery

Коли analyzer бачить `network_loading` або `network_error`, runner викликає:

```python
scenario.network_recovery_handler = lambda step, state: self._ask_network_recovery_action(
    account.email,
    step,
    state,
)
```

Очікувані відповіді:

| Action | Поведінка |
| --- | --- |
| `wait` | Почекати ще |
| `refresh` | Оновити сторінку |
| `cancel` | Зупинити сценарій |

Згідно з поточним рішенням проекту, після першого збою треба одразу питати користувача, а не робити автоматичні retry.

## CAPTCHA

CAPTCHA визначається через:

- `automation/captcha.py`
- `detect_captcha(driver)`
- `wait_for_captcha_solved(driver, timeout=...)`
- `handle_mexc_captcha(ctx, phase)`

Для MEXC-сценаріїв треба використовувати `handle_mexc_captcha(ctx, phase)`, бо він:

- пише короткі debug steps;
- робить screenshot/probe;
- викликає `captcha_service.notify(...)`;
- викликає `on_captcha_detected(...)`;
- чекає ручного вирішення;
- перевіряє cancel і закриту AdsPower-вкладку.

У checkpoint runner CAPTCHA підключається так:

```python
captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha")
```

Якщо action сам обробляє CAPTCHA, треба ставити:

```python
action_already_handles_captcha=True
```

## Email Code

Для MEXC email-кодів використовується `MexcEmailCodeFetcher` і helper:

```python
email_code = wait_mexc_email_code(self.ctx)
```

Під капотом використовується:

- `services/mexc_email_service.py`
- `wait_for_code(...)`
- `not_before_ts`
- `ignored_codes`
- `cancel_event`
- `cancel_checker`

Обов'язково передавати в `MexcBrowserContext`:

```python
cancel_event=self.cancel_event,
cancel_checker=self.browser_is_closed,
```

Це гарантує, що якщо користувач закрив AdsPower-вкладку під час очікування email-коду, сценарій негайно зупиниться.

## TOTP / 2FA Codes

Для MEXC використовується:

```python
fresh_totp_code(self.account.two_fa_secret, self.debug, "api_totp")
```

Цей helper:

- чекає новий 30-секундний цикл, якщо код майже протух;
- генерує код через `pyotp`;
- пише debug step без самого коду.

Правило: TOTP треба генерувати тільки після того, як email-код уже отриманий або email-крок уже точно пройдений.

## MEXC Browser Context

Для сценаріїв MEXC треба створювати `MexcBrowserContext`.

```python
self.ctx = MexcBrowserContext(
    driver=self.driver,
    account=self.account,
    debug=self.debug,
    email_fetcher=self.email_fetcher,
    captcha_service=self.captcha_service,
    task_id=self.task_id,
    on_captcha_detected=self.on_captcha_detected,
    on_email_timeout=self.on_email_timeout,
    manual_assist_handler=self.manual_assist_handler,
    network_recovery_handler=self.network_recovery_handler,
    state_analyzer=self.state_analyzer,
    cancel_event=self.cancel_event,
    cancel_checker=self.browser_is_closed,
)
```

Після цього можна використовувати helper-и:

| Helper | Призначення |
| --- | --- |
| `open_mexc_page(ctx, url, prefix)` | Відкрити сторінку і дочекатись `document.readyState == complete` |
| `ensure_mexc_logged_in(ctx, return_url, prefix)` | Перевірити login і залогінитись, якщо треба |
| `handle_mexc_captcha(ctx, phase)` | Виявити і чекати CAPTCHA |
| `click_get_code_if_active(ctx, timeout)` | Натиснути `Get Code` / `Send Code` |
| `wait_mexc_email_code(ctx)` | Дочекатись email verification code |
| `fresh_totp_code(secret, debug, prefix)` | Згенерувати свіжий TOTP |
| `clear_and_type(driver, element, value)` | Надійно очистити і ввести текст |
| `fill_named_code_input(...)` | Заповнити input за назвою/placeholder/label |
| `find_totp_input(...)` | Знайти Google Authenticator/TOTP input |
| `click_security_submit(...)` | Натиснути submit/confirm у security modal |
| `collect_error_text(driver)` | Зібрати видимі помилки |
| `security_modal_text(driver)` | Прочитати текст security modal |

## Progress І Користувацькі Повідомлення

Технічні debug steps не мають напряму показуватись користувачу.

Потік такий:

1. Сценарій викликає `self.debug.step("api_form_wait_done", ...)`.
2. `MexcRegistrationDebug` передає step у `progress_reporter`.
3. UI викликає `format_progress_step(...)`.
4. `automation/progress.py` повертає короткий `ProgressPresentation`.
5. UI записує короткий етап у журнал операцій.

Для нового сценарію треба додати formatter:

```python
if scenario_type == "new_scenario":
    return _format_new_scenario_step(normalized, data, level)
```

Правила тексту:

- коротко і зрозуміло;
- без stacktrace;
- без Selenium/ChromeDriver деталей;
- без секретів;
- для користувача показувати тільки важливі етапи.

## Сповіщення

Сповіщення всередині застосунку працюють через `OperationEventService`.

Основні події:

| Event type | Коли використовується |
| --- | --- |
| `task_completed` | Сценарій завершився успішно |
| `task_failed` | Сценарій завершився помилкою |
| `task_waiting_user` | Задача чекає рішення користувача |
| `manual_assist_required` | Потрібне ручне керування |
| `captcha_required` | Потрібно вирішити CAPTCHA |
| `account_create_completed` | Створено акаунт |
| `mexc_registration_completed` | MEXC registration завершена |

UI показує toast і програє звук для важливих подій:

- success: завершення операції;
- warning: manual assist / CAPTCHA / очікування користувача;
- error: помилка.

Для нового сценарію треба:

1. Запускати його через `_submit_scenario_task(...)`.
2. Повертати `ScenarioResult(success=True/False, ...)`.
3. Додати назву сценарію у `scenario_titles` в `ui/app.py`, якщо треба красивий текст.
4. Додати mapping у `automation/progress.py`.

## Запуск Сценарію З UI

Типовий запуск у `ui/app.py`:

```python
scenario = CreateMexcApiScenario(
    adspower=self.adspower,
    account=account,
    captcha_service=self.captcha_service,
    email_fetcher=email_fetcher,
    on_captcha_detected=lambda email: self.after(0, lambda: self._show_captcha_modal(email)),
    on_email_timeout=self._ask_wait_more_for_email_code,
)

scenario.manual_assist_handler = lambda step, states, initial: self._manual_assist_for_scenario(
    scenario,
    step,
    states,
    initial,
)

scenario.network_recovery_handler = lambda step, state: self._ask_network_recovery_action(
    account.email,
    step,
    state,
)

self._submit_scenario_task(
    "create_mexc_api",
    scenario,
    self._on_create_api_complete,
    "MEXC API creation started...",
)
```

`_submit_scenario_task(...)`:

- створює task через `TaskService`;
- прив'язує `task_id` до scenario/debug;
- підключає `progress_reporter`;
- запускає сценарій у фоні;
- викликає completion callback;
- забезпечує events і activity log.

## TaskService

`TaskService` відповідає за життєвий цикл задачі.

Основні методи:

| Метод | Призначення |
| --- | --- |
| `create_task(account_email, scenario_type)` | Створити задачу |
| `start_task(task_id)` | Позначити задачу як running |
| `complete_task(task_id, result)` | Позначити completed/failed і створити event |
| `fail_task(task_id, error)` | Завершити помилкою |
| `record_step(task_id, step, message, level, data)` | Записати короткий етап |
| `pause_for_user(...)` | Поставити задачу у waiting_user |
| `mark_retrying(task_id)` | Позначити retry |
| `get_recent_tasks(...)` | Отримати історію |

`complete_task(...)` додає `scenario_type` у event data. Це потрібно, щоб notifications знали, що завершилось: registration, 2FA, API тощо.

## OperationEventService

`OperationEventService`:

- створює `OperationEvent`;
- зберігає подію в database;
- тримає listeners;
- передає події в UI activity log і toast.

Основні методи:

| Метод | Призначення |
| --- | --- |
| `emit(...)` | Створити подію |
| `register_listener(callback)` | Підписати UI на події |
| `recent_for_account(account_email, limit)` | Історія акаунта |
| `recent_for_task(task_id, limit)` | Історія задачі |

## Debug Logs І Artifacts

Для MEXC сценаріїв використовується `MexcRegistrationDebug`.

Основні методи:

| Метод | Призначення |
| --- | --- |
| `bind_task(task_id)` | Прив'язати debug до task |
| `bind_progress_reporter(...)` | Передати step у UI progress |
| `with_secrets(...)` | Додати секрети для redaction |
| `step(name, **fields)` | Записати normal debug step |
| `warning(name, **fields)` | Записати warning |
| `save_screenshot(driver, filename)` | Зберегти screenshot |
| `save_page_probe(driver, filename)` | Зберегти DOM/page snapshot |
| `save_failure_artifacts(driver, reason)` | Зберегти artifacts при падінні |

Правила:

- деталі для розробника мають бути тільки в `logs/`;
- користувач у UI бачить короткі етапи;
- пароль, 2FA secret, email code, API key, secret key мають бути замасковані.

## Шаблон Нового Сценарію

```python
from automation.base import BaseScenario, ScenarioResult
from automation.checkpoints import CheckpointRunner, ScenarioCheckpoint


class NewScenario(BaseScenario):
    TARGET_URL = "https://example.com"

    def __init__(self, adspower, account, captcha_service=None):
        super().__init__(adspower, account, captcha_service)
        self.auto_close = False
        self.state_analyzer = SomePageStateAnalyzer()
        self.debug = SomeDebug(account_email=account.email)

    def run(self) -> ScenarioResult:
        self.debug.bind_task(self.task_id)
        self.debug.step("new_scenario_start")

        self._run_checkpoints()

        self.debug.step("new_scenario_success")
        return ScenarioResult(
            success=True,
            message=f"Scenario completed for {self.account.email}",
            data={"account_email": self.account.email},
        )

    def _run_checkpoints(self) -> None:
        runner = CheckpointRunner(
            driver_getter=lambda: self.driver,
            analyzer=self.state_analyzer,
            debug=self.debug,
            manual_assist_handler=self.manual_assist_handler,
            network_recovery_handler=self.network_recovery_handler,
            captcha_handler=lambda checkpoint: self._handle_captcha(f"{checkpoint}_captcha"),
        )
        runner.run(self._checkpoints())

    def _checkpoints(self) -> list[ScenarioCheckpoint]:
        return [
            ScenarioCheckpoint(
                name="open_page",
                action=self._open_page,
                allowed_states={"unknown", "network_loading", "network_error", "wrong_browser_tab"},
                done_states={"form_ready", "completed"},
                recover_wrong_tab=self._open_page,
            ),
            ScenarioCheckpoint(
                name="fill_form",
                action=self._fill_form,
                allowed_states={"form_ready"},
                done_states={"confirmation_open", "completed"},
                recover_wrong_tab=self._open_page,
            ),
            ScenarioCheckpoint(
                name="confirm",
                action=self._confirm,
                allowed_states={"confirmation_open"},
                done_states={"completed"},
                recover_wrong_tab=self._open_page,
            ),
        ]
```

## Checklist Для Нового Сценарію

Перед тим як вважати сценарій готовим, треба пройти список:

- Створений клас сценарію від `BaseScenario`.
- Усі довгі цикли перевіряють cancel і browser closed.
- Є `state_analyzer`.
- Додані всі потрібні states.
- Checkpoints мають `allowed_states` і `done_states`.
- Для wrong tab є `recover_wrong_tab`.
- Network states йдуть через `network_recovery_handler`.
- Manual assist підключений через UI.
- CAPTCHA підключена через handler.
- Email wait отримує `cancel_event` і `cancel_checker`.
- Секрети додані у debug redaction.
- `ScenarioResult.data` містить усе, що UI має зберегти.
- `automation/progress.py` має короткі messages для scenario_type.
- UI запускає сценарій через `_submit_scenario_task`.
- Completion callback зберігає результат у account/database.
- `task_completed` і `task_failed` доходять до notifications.
- Є py_compile перевірка.
- Реальний запуск зроблено вручну на тестовому акаунті.

## Типові Помилки

| Проблема | Як виправити |
| --- | --- |
| Сценарій постійно просить manual assist | Додати точніший state в analyzer або збільшити `done_states` |
| Сценарій починає заново замість продовження | Додати поточний state у `done_states` попереднього checkpoint-а |
| Сценарій чекає після закриття вкладки | Додати `_raise_if_browser_closed()` або `cancel_checker` |
| Analyzer плутає сторінки | Переставити priority у `_pick_state` або звузити DOM-сигнали |
| API/2FA вводить TOTP зарано | Генерувати TOTP тільки після email step |
| Користувач бачить технічний шум | Додати mapping у `automation/progress.py` |
| У logs видно секрет | Додати значення в `debug.with_secrets(...)` |
| Wrong tab не лікується | Додати `recover_wrong_tab=self._open_target_page` |
| CAPTCHA не визначається | Додати селектор або state-сигнал у analyzer |

## Поточні Реалізовані Сценарії

### Registration

Файл: `automation/scenarios/register_mexc.py`

Основні checkpoints:

- `open_registration_page`
- `fill_email`
- `fill_referral`
- `submit_email`
- `solve_captcha`
- `wait_email_code`
- `set_password`
- `verify_success`

### Link 2FA

Файл: `automation/scenarios/link_mexc_2fa.py`

Основні checkpoints:

- `open_security_page`
- `ensure_login`
- `download_authenticator`
- `extract_secret`
- `backup_key`
- `security_verification`
- `verify_success`

Особливість: якщо користувач вручну вже перейшов до security verification, сценарій може продовжити, але тільки якщо 2FA secret уже збережений.

### Create API

Файл: `automation/scenarios/create_mexc_api.py`

Основні checkpoints:

- `open_api_page`
- `ensure_login`
- `wait_api_form`
- `prepare_api_form`
- `submit_api_create`
- `security_verification`
- `extract_api_keys`
- `confirm_keys_saved`

Особливість: `api_created` не є terminal state, бо після нього ще треба витягнути `api_key` і `secret_key`.

## Рекомендований Порядок Розробки

1. Описати сценарій словами: які екрани, які inputs, які кінцеві результати.
2. Додати або уточнити analyzer states.
3. Написати checkpoints без складної логіки.
4. Реалізувати action-методи по одному.
5. Додати cancel/browser closed у всі цикли.
6. Підключити manual assist і network recovery.
7. Додати progress formatter.
8. Перевірити `py_compile`.
9. Запустити на тестовому акаунті.
10. Подивитись `logs/app.log` і artifacts.
11. Зменшити шум у UI, залишити технічні деталі тільки в logs.

