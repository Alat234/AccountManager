import customtkinter as ctk

from models.account import Account
from storage.constants import (
    STATUSES,
    normalize_ads_tag_color,
    readable_text_color,
)
from ui.widgets import EmailCodesWidget, TwoFactorAuthWidget, create_entry_with_copy

AUTOSAVE_DELAY_MS = 800


class DetailsTab:
    """Right panel account workspace."""

    def __init__(
        self,
        parent,
        copy_func,
        get_email_credentials,
        on_autosave=None,
        on_create_2fa=None,
        on_create_api=None,
        on_read_latest_deposit=None,
        on_find_deposit_screenshot=None,
        on_register_mexc=None,
        on_delete_account=None,
        on_upload_files=None,
        on_open_folder=None,
        on_refresh_rk_state=None,
        on_submit_rk=None,
        on_launch_adspower=None,
        on_unlink_adspower=None,
        on_remark_save=None,
    ):
        self.parent = parent
        self.copy_func = copy_func
        self.on_autosave = on_autosave
        self.on_create_2fa = on_create_2fa
        self.on_create_api = on_create_api
        self.on_read_latest_deposit = on_read_latest_deposit
        self.on_find_deposit_screenshot = on_find_deposit_screenshot
        self.on_register_mexc = on_register_mexc
        self.on_delete_account = on_delete_account
        self.on_upload_files = on_upload_files
        self.on_open_folder = on_open_folder
        self.on_refresh_rk_state = on_refresh_rk_state
        self.on_submit_rk = on_submit_rk
        self.on_launch_adspower = on_launch_adspower
        self.on_unlink_adspower = on_unlink_adspower
        self.on_remark_save = on_remark_save
        self._autosave_after_id = None
        self._current_email = None
        self._current_serial = 0
        self._current_profile_id = ""
        self._rk_deposit_rows = []

        self._build(parent, get_email_credentials)

    def _build(self, tab_main, get_email_credentials):
        tab_main.grid_columnconfigure(0, weight=1)
        tab_main.grid_rowconfigure(0, weight=1)

        self.scroll = ctk.CTkScrollableFrame(tab_main, fg_color="transparent")
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        self.header_card = ctk.CTkFrame(
            self.scroll,
            fg_color="#101418",
            corner_radius=8,
            border_width=1,
            border_color="#26313a",
        )
        self.header_card.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 8))
        self.header_card.grid_columnconfigure(1, weight=1)

        self.lbl_profile_number = ctk.CTkLabel(
            self.header_card,
            text="№ -",
            text_color="#7CFFB2",
            font=ctk.CTkFont(size=34, weight="bold"),
            width=120,
        )
        self.lbl_profile_number.grid(row=0, column=0, rowspan=2, sticky="w", padx=16, pady=12)

        self.lbl_editing_status = ctk.CTkLabel(
            self.header_card,
            text="Акаунт не вибрано",
            font=ctk.CTkFont(size=20, weight="bold"),
            anchor="w",
        )
        self.lbl_editing_status.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=(14, 0))

        self.lbl_profile_id = ctk.CTkLabel(
            self.header_card,
            text="AdsPower ID: -",
            text_color="#9aa4ad",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self.lbl_profile_id.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(0, 14))

        self.btn_delete_account = ctk.CTkButton(
            self.header_card,
            text="Видалити",
            width=110,
            fg_color="#8b0000",
            hover_color="#5c0000",
            command=self._on_delete_account,
        )
        self.btn_delete_account.grid(row=0, column=2, rowspan=2, sticky="ne", padx=14, pady=14)

        main_container = ctk.CTkFrame(self.scroll, fg_color="transparent")
        main_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        main_container.grid_columnconfigure(0, weight=38)
        main_container.grid_columnconfigure(1, weight=32)
        main_container.grid_columnconfigure(2, weight=30)

        left_side = ctk.CTkFrame(main_container, fg_color="transparent")
        left_side.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        middle_side = ctk.CTkFrame(main_container, fg_color="transparent")
        middle_side.grid(row=0, column=1, sticky="nsew", padx=8)

        right_side = ctk.CTkFrame(main_container, fg_color="transparent")
        right_side.grid(row=0, column=2, sticky="nsew", padx=(8, 0))

        profile_card = self._card(left_side, "Профіль")
        profile_card.pack(fill="x", pady=(0, 12))
        profile_inner = ctk.CTkFrame(profile_card, fg_color="transparent")
        profile_inner.pack(fill="x", padx=12, pady=(0, 12))
        profile_inner.grid_columnconfigure(0, weight=1)

        self._field_label(profile_inner, "Головна пошта", 0, 0)

        frame_main_email, self.entry_main_email = create_entry_with_copy(
            profile_inner,
            self.copy_func,
            font=ctk.CTkFont(weight="bold"),
        )
        frame_main_email.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))

        self._field_label(profile_inner, "Пароль", 2, 0)
        frame_pass, self.entry_pass = create_entry_with_copy(profile_inner, self.copy_func)
        frame_pass.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 10))

        self._field_label(profile_inner, "Теги AdsPower", 4, 0)
        self.tags_frame = ctk.CTkFrame(profile_inner, fg_color="#17191c", corner_radius=6, height=34)
        self.tags_frame.grid(row=5, column=0, sticky="ew", padx=5, pady=(0, 10))
        self.tags_frame.pack_propagate(False)

        self._field_label(profile_inner, "Зауваження / remark", 6, 0)
        self.entry_ads_remark = ctk.CTkTextbox(profile_inner, height=76, wrap="word")
        self.entry_ads_remark.grid(row=7, column=0, sticky="ew", padx=5, pady=(0, 8))
        profile_buttons = ctk.CTkFrame(profile_inner, fg_color="transparent")
        profile_buttons.grid(row=8, column=0, sticky="ew", padx=5, pady=(0, 2))
        profile_buttons.grid_columnconfigure((0, 1), weight=1)
        self.btn_register_mexc = ctk.CTkButton(
            profile_buttons,
            text="Register",
            fg_color="#1f538d",
            hover_color="#143a63",
            command=self._on_register_mexc,
        )
        self.btn_register_mexc.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.btn_save_remark = ctk.CTkButton(
            profile_buttons,
            text="Синхр. ADS",
            height=32,
            fg_color="#1f538d",
            hover_color="#143a63",
            command=self._on_remark_save,
        )
        self.btn_save_remark.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ads_buttons = ctk.CTkFrame(profile_inner, fg_color="transparent")
        ads_buttons.grid(row=9, column=0, sticky="ew", padx=5, pady=(8, 2))
        ads_buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            ads_buttons,
            text="Відкрити ADS",
            command=self._on_launch_adspower,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            ads_buttons,
            text="Відв'язати",
            fg_color="#6a4c93",
            hover_color="#4a3570",
            command=self._on_unlink_adspower,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        rk_card = self._card(middle_side, "RK")
        rk_card.pack(fill="x", pady=(0, 12))
        rk_inner = ctk.CTkFrame(rk_card, fg_color="transparent")
        rk_inner.pack(fill="x", padx=12, pady=(0, 12))
        rk_inner.grid_columnconfigure(0, weight=1)
        rk_top = ctk.CTkFrame(rk_inner, fg_color="transparent")
        rk_top.grid(row=0, column=0, sticky="ew", padx=5, pady=(0, 8))
        rk_top.grid_columnconfigure(0, weight=1)
        self.rk_summary_label = ctk.CTkLabel(rk_top, text="Файли RK", text_color="#dce4ee", anchor="w")
        self.rk_summary_label.grid(row=0, column=0, sticky="ew")
        self.btn_refresh_rk = ctk.CTkButton(
            rk_top,
            text="↻",
            width=34,
            fg_color="#343638",
            hover_color="#1f538d",
            command=self._on_refresh_rk_state,
        )
        self.btn_refresh_rk.grid(row=0, column=1, sticky="e")

        self.rk_bank_row, self.rk_bank_dot, self.rk_bank_label = self._rk_status_row(
            rk_inner,
            "Bank statement PDF",
            1,
        )
        self.rk_deposits_frame = ctk.CTkFrame(rk_inner, fg_color="#17191c", corner_radius=6)
        self.rk_deposits_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=(4, 10))

        rk_buttons = ctk.CTkFrame(rk_inner, fg_color="transparent")
        rk_buttons.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 8))
        rk_buttons.grid_columnconfigure(0, weight=1)
        self.btn_latest_deposit = ctk.CTkButton(
            rk_buttons,
            text="Find RK Deposits",
            fg_color="#2f6f52",
            hover_color="#255842",
            command=self._on_read_latest_deposit,
        )
        self.btn_latest_deposit.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.btn_find_deposit_screenshot = ctk.CTkButton(
            rk_buttons,
            text="Make Deposit Screenshot",
            fg_color="#7a5c1e",
            hover_color="#5d4617",
            state="disabled",
            command=self._on_find_deposit_screenshot,
        )
        self.btn_find_deposit_screenshot.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.btn_submit_rk = ctk.CTkButton(
            rk_buttons,
            text="Submit RK",
            fg_color="#8b5cf6",
            hover_color="#6d28d9",
            command=self._on_submit_rk,
        )
        self.btn_submit_rk.grid(row=2, column=0, sticky="ew")

        files_card = self._card(middle_side, "Файли")
        files_card.pack(fill="x", pady=(0, 12))
        files_inner = ctk.CTkFrame(files_card, fg_color="transparent")
        files_inner.pack(fill="x", padx=12, pady=(0, 12))
        files_inner.grid_columnconfigure(0, weight=1)
        self._field_label(files_inner, "Статус / папка", 0, 0)
        self.status_var = ctk.StringVar(value=STATUSES[0])
        self.opt_status = ctk.CTkOptionMenu(
            files_inner,
            values=STATUSES,
            variable=self.status_var,
            command=lambda _choice: self._schedule_autosave(),
        )
        self.opt_status.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))
        file_buttons = ctk.CTkFrame(files_inner, fg_color="transparent")
        file_buttons.grid(row=2, column=0, sticky="ew", padx=5, pady=(0, 2))
        file_buttons.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(file_buttons, text="Завантажити", command=self._on_upload_files).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ctk.CTkButton(file_buttons, text="Папка", command=self._on_open_folder).grid(
            row=0, column=1, sticky="ew", padx=(4, 0)
        )

        self.two_fa_widget = TwoFactorAuthWidget(
            right_side,
            self.copy_func,
            on_create_2fa=self.on_create_2fa,
        )
        self.two_fa_widget.pack(fill="x", pady=(0, 12))

        security_card = self._card(right_side, "API MEXC")
        security_card.pack(fill="x", pady=(0, 12))
        access_inner = ctk.CTkFrame(security_card, fg_color="transparent")
        access_inner.pack(fill="x", padx=12, pady=(0, 12))
        access_inner.grid_columnconfigure(0, weight=1)

        self._field_label(access_inner, "API Key", 0, 0)
        frame_api, self.entry_api = create_entry_with_copy(access_inner, self.copy_func)
        self.btn_create_api = ctk.CTkButton(
            frame_api,
            text="Create API",
            width=90,
            fg_color="#1f538d",
            hover_color="#143a63",
            command=self._on_create_api,
        )
        self.btn_create_api.grid(row=0, column=2, padx=(5, 0))
        frame_api.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))

        self._field_label(access_inner, "Secret Key", 2, 0)
        frame_secret, self.entry_secret = create_entry_with_copy(access_inner, self.copy_func)
        frame_secret.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 10))

        self.email_codes_widget = EmailCodesWidget(right_side, self.copy_func, get_email_credentials, compact=True)
        self.email_codes_widget.pack(fill="x", expand=False)

        self._setup_autosave_bindings()

    @staticmethod
    def _card(parent, title):
        card = ctk.CTkFrame(
            parent,
            fg_color="#212121",
            corner_radius=8,
            border_width=1,
            border_color="#343638",
        )
        ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(10, 6), padx=15, anchor="w")
        return card

    @staticmethod
    def _field_label(parent, text, row, column):
        ctk.CTkLabel(parent, text=text, text_color="gray").grid(
            row=row,
            column=column,
            sticky="w",
            padx=5,
            pady=(5, 0),
        )

    @staticmethod
    def _rk_status_row(parent, text, row):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=5, pady=3)
        frame.grid_columnconfigure(1, weight=1)
        dot = ctk.CTkLabel(
            frame,
            text="✕",
            width=26,
            height=24,
            corner_radius=12,
            fg_color="#7f1d1d",
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        dot.grid(row=0, column=0, sticky="w", padx=(0, 8))
        label = ctk.CTkLabel(frame, text=text, anchor="w")
        label.grid(row=0, column=1, sticky="ew")
        return frame, dot, label

    @staticmethod
    def _set_status_dot(dot, ok: bool):
        dot.configure(
            text="✓" if ok else "✕",
            fg_color="#166534" if ok else "#7f1d1d",
        )

    def update_rk_state(self, state: dict | None):
        state = state or {}
        bank_ok = bool(state.get("bank_statement_exists"))
        deposits = state.get("selected_deposits") or []

        self._set_status_dot(self.rk_bank_dot, bank_ok)
        self.rk_bank_label.configure(
            text="Bank statement PDF" if bank_ok else "Bank statement PDF missing"
        )

        for widget in self.rk_deposits_frame.winfo_children():
            widget.destroy()
        self._rk_deposit_rows = []

        if not deposits:
            ctk.CTkLabel(
                self.rk_deposits_frame,
                text="Немає вибраних RK депозитів",
                text_color="gray",
            ).pack(anchor="w", padx=10, pady=10)
            self.rk_summary_label.configure(text="RK: deposits not selected")
            self.btn_find_deposit_screenshot.configure(state="disabled")
            return

        loaded_count = 0
        for deposit in deposits:
            row = ctk.CTkFrame(self.rk_deposits_frame, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=3)
            row.grid_columnconfigure(1, weight=1)
            ok = bool(deposit.get("screenshot_exists"))
            loaded_count += 1 if ok else 0
            dot = ctk.CTkLabel(
                row,
                text="✓" if ok else "✕",
                width=24,
                height=22,
                corner_radius=11,
                fg_color="#166534" if ok else "#7f1d1d",
                text_color="white",
                font=ctk.CTkFont(size=12, weight="bold"),
            )
            dot.grid(row=0, column=0, sticky="w", padx=(0, 8))
            label = ctk.CTkLabel(row, text=deposit.get("label") or "Deposit screenshot", anchor="w")
            label.grid(row=0, column=1, sticky="ew")
            self._rk_deposit_rows.append((dot, label))

        self.rk_summary_label.configure(text=f"RK: {loaded_count}/{len(deposits)} screenshots")
        self.btn_find_deposit_screenshot.configure(state="normal")

    def _setup_autosave_bindings(self):
        for entry in (
            self.entry_pass,
            self.entry_api,
            self.entry_secret,
            self.two_fa_widget.entry_secret,
        ):
            entry.bind("<KeyRelease>", lambda _event: self._schedule_autosave())
        self.entry_ads_remark.bind("<KeyRelease>", lambda _event: self._schedule_autosave())

    def display(self, account: Account, tags=None):
        self._current_email = account.email
        self._current_serial = account.ads_serial_number
        self._current_profile_id = account.ads_profile_id
        number = account.ads_serial_number if account.ads_serial_number else "-"
        self.lbl_profile_number.configure(text=f"№ {number}")
        self.lbl_editing_status.configure(text=account.email)
        self.lbl_profile_id.configure(text=f"AdsPower ID: {account.ads_profile_id or '-'}")

        self.entry_main_email.delete(0, "end")
        self.entry_main_email.insert(0, account.email)
        self.entry_pass.delete(0, "end")
        self.entry_pass.insert(0, account.password)
        self.entry_api.delete(0, "end")
        self.entry_api.insert(0, account.api_key)
        self.entry_secret.delete(0, "end")
        self.entry_secret.insert(0, account.secret_key)
        self.two_fa_widget.set_secret(account.two_fa_secret)
        self.status_var.set(account.status if account.status else STATUSES[0])
        self.entry_ads_remark.delete("1.0", "end")
        self.entry_ads_remark.insert("1.0", account.ads_remark or "")
        self._render_tags(tags or [])

        for widget in self.email_codes_widget.codes_frame.winfo_children():
            widget.destroy()
        self.email_codes_widget.lbl_status.configure(
            text="Натисніть 'Оновити' або увімкніть Авто",
            text_color="gray",
        )
        self.email_codes_widget.auto_var.set(False)
        self.email_codes_widget.last_found_code = None
        self.update_rk_state({})

    @staticmethod
    def _set_disabled_entry(entry, value):
        entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, value)
        entry.configure(state="disabled")

    def _render_tags(self, tags):
        for widget in self.tags_frame.winfo_children():
            widget.destroy()
        if not tags:
            ctk.CTkLabel(
                self.tags_frame,
                text="Тегів немає",
                text_color="gray",
                font=ctk.CTkFont(size=12),
            ).pack(side="left", padx=10, pady=7)
            return
        for tag in tags:
            color = normalize_ads_tag_color(tag.get("color", ""))
            ctk.CTkLabel(
                self.tags_frame,
                text=tag.get("name", ""),
                fg_color=color,
                corner_radius=4,
                text_color=readable_text_color(color),
                font=ctk.CTkFont(size=11, weight="bold"),
                height=22,
                padx=6,
            ).pack(side="left", padx=(8, 0), pady=6)

    def collect(self) -> Account:
        acc = Account(
            email=self._current_email or self.entry_main_email.get().strip(),
            password=self.entry_pass.get(),
            api_key=self.entry_api.get(),
            secret_key=self.entry_secret.get(),
            two_fa_secret=self.two_fa_widget.get_secret(),
            old_email="",
            status=self.status_var.get(),
            ads_serial_number=self._current_serial,
            ads_profile_id=self._current_profile_id,
            ads_remark=self.entry_ads_remark.get("1.0", "end").strip(),
        )
        return acc

    def get_entered_email(self) -> str:
        return self.entry_main_email.get().strip()

    def set_entered_email(self, email: str):
        self.entry_main_email.delete(0, "end")
        self.entry_main_email.insert(0, email)

    def update_profit(self, _account: Account):
        return

    def clear(self):
        self._current_email = None
        self._current_serial = 0
        self._current_profile_id = ""
        self.lbl_profile_number.configure(text="№ -")
        self.lbl_profile_id.configure(text="AdsPower ID: -")
        self.lbl_editing_status.configure(text="Акаунт не вибрано")
        self.entry_main_email.delete(0, "end")
        self.entry_pass.delete(0, "end")
        self.entry_api.delete(0, "end")
        self.entry_secret.delete(0, "end")
        self.entry_ads_remark.delete("1.0", "end")
        self.two_fa_widget.set_secret("")
        self._render_tags([])
        self.update_rk_state({})

    def _schedule_autosave(self):
        if not self._current_email:
            return
        self._cancel_autosave()
        self._autosave_after_id = self.parent.after(AUTOSAVE_DELAY_MS, self._fire_autosave)

    def _cancel_autosave(self):
        if self._autosave_after_id is not None:
            try:
                self.parent.after_cancel(self._autosave_after_id)
            except Exception:
                pass
            self._autosave_after_id = None

    def _fire_autosave(self):
        self._autosave_after_id = None
        if self.on_autosave:
            self.on_autosave()

    def flush_autosave(self):
        if self._autosave_after_id is not None:
            self._cancel_autosave()
            if self.on_autosave:
                self.on_autosave(silent=True)

    def dispose(self):
        self._cancel_autosave()
        self.two_fa_widget.stop()
        self.email_codes_widget.stop()

    def _on_create_api(self):
        if self.on_create_api:
            self.on_create_api()

    def _on_read_latest_deposit(self):
        if self.on_read_latest_deposit:
            self.on_read_latest_deposit()

    def _on_find_deposit_screenshot(self):
        if self.on_find_deposit_screenshot:
            self.on_find_deposit_screenshot()

    def _on_remark_save(self):
        if self.on_remark_save and self._current_email:
            self.on_remark_save(self._current_email, self.entry_ads_remark.get("1.0", "end").strip())

    def _on_register_mexc(self):
        if self.on_register_mexc:
            self.on_register_mexc()

    def _on_delete_account(self):
        if self.on_delete_account:
            self.on_delete_account()

    def _on_upload_files(self):
        if self.on_upload_files:
            self.on_upload_files()

    def _on_open_folder(self):
        if self.on_open_folder:
            self.on_open_folder()

    def _on_refresh_rk_state(self):
        if self.on_refresh_rk_state:
            self.on_refresh_rk_state()

    def _on_submit_rk(self):
        if self.on_submit_rk:
            self.on_submit_rk()

    def _on_launch_adspower(self):
        if self.on_launch_adspower:
            self.on_launch_adspower()

    def _on_unlink_adspower(self):
        if self.on_unlink_adspower:
            self.on_unlink_adspower()
