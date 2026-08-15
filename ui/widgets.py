import customtkinter as ctk
import pyotp
import time
import threading


def create_entry_with_copy(parent, copy_func, font=None):
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)
    entry = ctk.CTkEntry(frame, font=font)
    entry.grid(row=0, column=0, sticky="ew")
    btn_copy = ctk.CTkButton(frame, text="📋", width=28, fg_color="#343638", hover_color="#1f538d",
                             command=lambda: copy_func(entry.get()))
    btn_copy.grid(row=0, column=1, padx=(5, 0))
    return frame, entry


class TwoFactorAuthWidget(ctk.CTkFrame):
    def __init__(self, master, copy_func, on_create_2fa=None):
        super().__init__(master, fg_color="#212121", corner_radius=10, border_width=1, border_color="#343638")
        self.copy_func = copy_func
        self.on_create_2fa = on_create_2fa

        ctk.CTkLabel(self, text="🔐 2FA Аутентифікатор", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5))

        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(pady=5, padx=10, fill="x")
        self.entry_secret = ctk.CTkEntry(input_frame, placeholder_text="Введіть 2FA Secret Key", width=180)
        self.entry_secret.pack(side="left", padx=5, fill="x", expand=True)

        self.lbl_code = ctk.CTkLabel(self, text="------", font=ctk.CTkFont(size=32, weight="bold", family="Courier"))
        self.lbl_code.pack(pady=(5, 0))

        self.progress = ctk.CTkProgressBar(self, width=180, progress_color="#1fa5ff")
        self.progress.set(0)
        self.progress.pack(pady=(5, 5))

        self.lbl_timer = ctk.CTkLabel(self, text="Очікування ключа...", text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_timer.pack(pady=(0, 5))

        self.btn_copy_code = ctk.CTkButton(self, text="📋 Скопіювати код", fg_color="#1f538d", hover_color="#143a63",
                                           command=self.copy_current_code)
        self.btn_copy_code.pack(pady=(0, 15))

        self.btn_create_2fa = ctk.CTkButton(
            self,
            text="Create 2FA/Link 2FA",
            fg_color="#0f766e",
            hover_color="#115e59",
            command=self._on_create_2fa,
        )
        self.btn_create_2fa.pack(pady=(0, 15), padx=10, fill="x")

        # Кеш останнього показаного стану — щоб не перемальовувати віджети щосекунди дарма
        self._last_code = None
        self._last_state = None
        self._clock_after_id = None
        self.update_clock()

    def set_secret(self, secret):
        self._cancel_clock()
        self._last_code = None
        self._last_state = None
        self.entry_secret.delete(0, 'end')
        if secret: self.entry_secret.insert(0, secret)
        self.update_clock()

    def get_secret(self):
        return self.entry_secret.get().strip().replace(" ", "").upper()

    def copy_current_code(self):
        code = self.lbl_code.cget("text").replace(" ", "")
        if code and code.isdigit(): self.copy_func(code)

    def _on_create_2fa(self):
        if self.on_create_2fa:
            self.on_create_2fa()

    def update_clock(self):
        self._clock_after_id = None
        current_secret = self.get_secret()
        if not current_secret:
            if self._last_state != "empty":
                self._last_state = "empty"
                self._last_code = None
                self.lbl_code.configure(text="------", text_color="gray")
                self.progress.set(0)
                self.lbl_timer.configure(text="Введіть Secret Key", text_color="gray")
        else:
            try:
                totp = pyotp.TOTP(current_secret)
                code = totp.now()
                time_remaining = 30 - (int(time.time()) % 30)
                state = "warn" if time_remaining <= 5 else "ok"

                # Текст коду оновлюємо лише коли код реально змінився
                if code != self._last_code:
                    self._last_code = code
                    self.lbl_code.configure(text=f"{code[:3]} {code[3:]}")

                # Кольори/режим — лише при зміні стану (раз на цикл, а не щосекунди)
                if state != self._last_state:
                    self._last_state = state
                    if state == "warn":
                        self.progress.configure(progress_color="#ff4444")
                        self.lbl_code.configure(text_color="#ff4444")
                    else:
                        self.progress.configure(progress_color="#00ff00")
                        self.lbl_code.configure(text_color="white")

                # Прогрес-бар і лічильник секунд оновлюються щосекунди (це дешево)
                self.progress.set(time_remaining / 30.0)
                if state == "warn":
                    self.lbl_timer.configure(text=f"Увага! Оновлення через {time_remaining} с", text_color="#ff4444")
                else:
                    self.lbl_timer.configure(text=f"Дійсний ще {time_remaining} сек", text_color="gray")
            except Exception:
                if self._last_state != "error":
                    self._last_state = "error"
                    self._last_code = None
                    self.lbl_code.configure(text="ПОМИЛКА", text_color="#ff4444")
                    self.progress.set(0)
                    self.progress.configure(progress_color="#ff4444")
                    self.lbl_timer.configure(text="Невірний формат ключа!", text_color="#ff4444")
        self._schedule_clock()

    def _schedule_clock(self):
        if self._clock_after_id is None:
            self._clock_after_id = self.after(1000, self.update_clock)

    def _cancel_clock(self):
        if self._clock_after_id is None:
            return
        try:
            self.after_cancel(self._clock_after_id)
        except Exception:
            pass
        self._clock_after_id = None

    def stop(self):
        self._cancel_clock()


class EmailCodesWidget(ctk.CTkFrame):
    def __init__(self, master, copy_func, get_credentials_func):
        super().__init__(master, fg_color="#212121", corner_radius=10, border_width=1, border_color="#343638")
        self.copy_func = copy_func
        self.get_credentials_func = get_credentials_func

        self.is_fetching = False
        self.last_found_code = None  # Зберігаємо останній код, щоб не пікати двічі на одне й те саме
        self._auto_after_id = None

        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=10, pady=(10, 5))

        ctk.CTkLabel(top_frame, text="📩 Останній код з пошти", font=ctk.CTkFont(size=14, weight="bold")).pack(
            side="left")

        # НОВИЙ ПЕРЕМИКАЧ АВТО-ПОШУКУ
        self.auto_var = ctk.BooleanVar(value=False)
        self.switch_auto = ctk.CTkSwitch(top_frame, text="Авто", variable=self.auto_var, command=self.on_auto_toggle,
                                         width=60, progress_color="green")
        self.switch_auto.pack(side="right", padx=(10, 0))

        self.btn_refresh = ctk.CTkButton(top_frame, text="🔄", width=40, fg_color="#b35b04", hover_color="#d9710b",
                                         command=self.start_fetch_thread)
        self.btn_refresh.pack(side="right")

        self.lbl_status = ctk.CTkLabel(self, text="Натисніть 'Оновити' або увімкніть Авто", text_color="gray",
                                       font=ctk.CTkFont(size=11), wraplength=250)
        self.lbl_status.pack(pady=2)

        self.codes_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.codes_frame.pack(fill="both", expand=True, padx=10, pady=5)

    def on_auto_toggle(self):
        """Обробка натискання перемикача 'Авто'"""
        if self.auto_var.get():
            self._cancel_auto_refresh()
            self.lbl_status.configure(text="Режим очікування увімкнено...", text_color="#1fa5ff")
            if not self.is_fetching:
                self.start_fetch_thread()
        else:
            self._cancel_auto_refresh()
            self.lbl_status.configure(text="Авто-пошук зупинено", text_color="gray")
            self.btn_refresh.configure(state="normal")

    def start_fetch_thread(self):
        if self.is_fetching: return

        mailboxes, target = self.get_credentials_func()
        if not target:
            self.lbl_status.configure(text="Виберіть акаунт!", text_color="red")
            self.auto_var.set(False)
            return
        if not mailboxes:
            self.lbl_status.configure(text="Додайте пошти в Налаштуваннях!", text_color="red")
            self.auto_var.set(False)
            return

        self.is_fetching = True
        self.btn_refresh.configure(state="disabled")

        if not self.auto_var.get():
            self.lbl_status.configure(text="Шукаю...", text_color="yellow")

        # Фоновий потік, щоб інтерфейс не зависав (daemon — не тримає процес при закритті)
        thread = threading.Thread(target=self._fetch_in_background, args=(mailboxes, target), daemon=True)
        thread.start()

    def _fetch_in_background(self, mailboxes, target):
        from email_parser import fetch_mexc_codes
        all_errors = []
        for mb in mailboxes:
            user, pwd, server = mb[0], mb[1], mb[2]
            res = fetch_mexc_codes(server, user, pwd, target)

            if "data" in res and res["data"]:
                self.after(0, lambda r=res: self._update_ui_with_results(r))
                return
            elif "error" in res:
                all_errors.append(f"{user}: {res['error']}")

        if all_errors:
            self.after(0, lambda: self._update_ui_with_results({"error": "\n".join(all_errors)}))
        else:
            self.after(0, lambda: self._update_ui_with_results({"data": []}))

    def _update_ui_with_results(self, result):
        self.is_fetching = False

        if not self.auto_var.get():
            self.btn_refresh.configure(state="normal")

        if "error" in result:
            self.lbl_status.configure(text=result["error"], text_color="red")
            self.auto_var.set(False)  # Вимикаємо авто-пошук при помилці
            self.btn_refresh.configure(state="normal")
            return

        data = result["data"]

        if not data:
            if self.auto_var.get():
                self.lbl_status.configure(text="Очікую нові листи (Оновлення кожні 4с)...", text_color="gray")
            else:
                self.lbl_status.configure(text="Кодів не знайдено", text_color="gray")
        else:
            # Отримали свіжий код
            new_code = data[0]["code"]
            time_str = data[0]["time"]

            # Якщо це НОВИЙ код, якого ми ще не бачили
            if new_code != self.last_found_code:
                self.last_found_code = new_code

                # Відтворюємо системний звук Windows (Дінь!)
                try:
                    import winsound
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                except:
                    pass

                self.lbl_status.configure(text=f"Знайдено новий код!", text_color="#00ff00")

                # Оновлюємо інтерфейс (видаляємо старі, малюємо новий)
                for widget in self.codes_frame.winfo_children(): widget.destroy()

                row = ctk.CTkFrame(self.codes_frame, fg_color="#1f538d",
                                   corner_radius=5)  # Синій фон для привернення уваги
                row.pack(fill="x", pady=2)

                ctk.CTkLabel(row, text=time_str, text_color="#dce4ee", width=80).pack(side="left", padx=10)
                ctk.CTkLabel(row, text=new_code, font=ctk.CTkFont(weight="bold", size=22), text_color="white").pack(
                    side="left", padx=10)

                ctk.CTkButton(row, text="📋 Копіювати", width=30, fg_color="#b35b04", hover_color="#d9710b",
                              command=lambda c=new_code: self.copy_func(c)).pack(side="right", padx=10, pady=10)

        # ЛОГІКА ЗУПИНКИ / ПРОДОВЖЕННЯ АВТО-ПОШУКУ
        if self.auto_var.get():
            # Запускаємо знову через 4 секунди
            self._cancel_auto_refresh()
            self._auto_after_id = self.after(4000, self.start_fetch_thread)

    def _cancel_auto_refresh(self):
        if self._auto_after_id is None:
            return
        try:
            self.after_cancel(self._auto_after_id)
        except Exception:
            pass
        self._auto_after_id = None

    def stop(self):
        self.auto_var.set(False)
        self._cancel_auto_refresh()
