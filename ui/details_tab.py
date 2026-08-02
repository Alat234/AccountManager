import customtkinter as ctk

from models.account import Account
from storage.constants import (
    ADS_TAG_COLORS,
    ADS_TAG_DEFAULT_COLOR,
    STATUSES,
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
        on_remark_save=None,
    ):
        self.parent = parent
        self.copy_func = copy_func
        self.on_autosave = on_autosave
        self.on_create_2fa = on_create_2fa
        self.on_create_api = on_create_api
        self.on_remark_save = on_remark_save
        self._autosave_after_id = None
        self._current_email = None
        self._current_serial = 0
        self._current_profile_id = ""

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

        main_container = ctk.CTkFrame(self.scroll, fg_color="transparent")
        main_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        main_container.grid_columnconfigure(0, weight=6)
        main_container.grid_columnconfigure(1, weight=4)

        left_side = ctk.CTkFrame(main_container, fg_color="transparent")
        left_side.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right_side = ctk.CTkFrame(main_container, fg_color="transparent")
        right_side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        profile_card = self._card(left_side, "Профіль")
        profile_card.pack(fill="x", pady=(0, 12))
        profile_inner = ctk.CTkFrame(profile_card, fg_color="transparent")
        profile_inner.pack(fill="x", padx=12, pady=(0, 12))
        profile_inner.grid_columnconfigure((0, 1), weight=1)

        self._field_label(profile_inner, "№ AdsPower", 0, 0)
        self.entry_ads_serial = ctk.CTkEntry(profile_inner)
        self.entry_ads_serial.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))
        self.entry_ads_serial.configure(state="disabled")

        self._field_label(profile_inner, "Статус / папка", 0, 1)
        self.status_var = ctk.StringVar(value=STATUSES[0])
        self.opt_status = ctk.CTkOptionMenu(
            profile_inner,
            values=STATUSES,
            variable=self.status_var,
            command=lambda _choice: self._schedule_autosave(),
        )
        self.opt_status.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 10))

        self._field_label(profile_inner, "Головна пошта", 2, 0)
        self._field_label(profile_inner, "Пароль", 2, 1)

        frame_main_email, self.entry_main_email = create_entry_with_copy(
            profile_inner,
            self.copy_func,
            font=ctk.CTkFont(weight="bold"),
        )
        frame_main_email.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 10))

        frame_pass, self.entry_pass = create_entry_with_copy(profile_inner, self.copy_func)
        frame_pass.grid(row=3, column=1, sticky="ew", padx=5, pady=(0, 10))

        self._field_label(profile_inner, "Теги AdsPower", 4, 0)
        self.tags_frame = ctk.CTkFrame(profile_inner, fg_color="#17191c", corner_radius=6, height=34)
        self.tags_frame.grid(row=5, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 10))
        self.tags_frame.pack_propagate(False)

        self._field_label(profile_inner, "Зауваження / remark", 6, 0)
        remark_frame = ctk.CTkFrame(profile_inner, fg_color="transparent")
        remark_frame.grid(row=7, column=0, columnspan=2, sticky="ew", padx=5, pady=(0, 2))
        remark_frame.grid_columnconfigure(0, weight=1)
        self.entry_ads_remark = ctk.CTkTextbox(remark_frame, height=72, wrap="word")
        self.entry_ads_remark.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.btn_save_remark = ctk.CTkButton(
            remark_frame,
            text="Синхр. ADS",
            width=96,
            height=32,
            fg_color="#1f538d",
            hover_color="#143a63",
            command=self._on_remark_save,
        )
        self.btn_save_remark.grid(row=0, column=1, sticky="n")

        security_card = self._card(left_side, "API MEXC")
        security_card.pack(fill="x", pady=(0, 12))
        access_inner = ctk.CTkFrame(security_card, fg_color="transparent")
        access_inner.pack(fill="x", padx=12, pady=(0, 12))
        access_inner.grid_columnconfigure((0, 1), weight=1)

        self._field_label(access_inner, "API Key", 0, 0)
        self._field_label(access_inner, "Secret Key", 0, 1)

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

        frame_secret, self.entry_secret = create_entry_with_copy(access_inner, self.copy_func)
        frame_secret.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 10))

        self.two_fa_widget = TwoFactorAuthWidget(
            right_side,
            self.copy_func,
            on_create_2fa=self.on_create_2fa,
        )
        self.two_fa_widget.pack(fill="x", pady=(0, 12))

        self.email_codes_widget = EmailCodesWidget(right_side, self.copy_func, get_email_credentials)
        self.email_codes_widget.pack(fill="both", expand=True)

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

        self._set_disabled_entry(self.entry_ads_serial, str(account.ads_serial_number or ""))
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
            color = ADS_TAG_COLORS.get(tag.get("color", ""), ADS_TAG_DEFAULT_COLOR)
            text_color = "#000000" if tag.get("color") == "yellow" else "white"
            ctk.CTkLabel(
                self.tags_frame,
                text=tag.get("name", ""),
                fg_color=color,
                corner_radius=4,
                text_color=text_color,
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
        self._set_disabled_entry(self.entry_ads_serial, "")
        self.entry_main_email.delete(0, "end")
        self.entry_pass.delete(0, "end")
        self.entry_api.delete(0, "end")
        self.entry_secret.delete(0, "end")
        self.entry_ads_remark.delete("1.0", "end")
        self.two_fa_widget.set_secret("")
        self._render_tags([])

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

    def _on_create_api(self):
        if self.on_create_api:
            self.on_create_api()

    def _on_remark_save(self):
        if self.on_remark_save and self._current_email:
            self.on_remark_save(self._current_email, self.entry_ads_remark.get("1.0", "end").strip())
