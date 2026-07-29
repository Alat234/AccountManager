import customtkinter as ctk

from models.account import Account
from storage.constants import STATUSES
from ui.widgets import create_entry_with_copy, TwoFactorAuthWidget, EmailCodesWidget

AUTOSAVE_DELAY_MS = 800


class DetailsTab:
    """Right panel 'Деталі' tab — account fields, finances, 2FA, email codes."""

    def __init__(
        self,
        parent,
        copy_func,
        get_email_credentials,
        on_autosave=None,
        on_create_2fa=None,
        on_create_api=None,
    ):
        self.parent = parent
        self.copy_func = copy_func
        self.on_autosave = on_autosave
        self.on_create_2fa = on_create_2fa
        self.on_create_api = on_create_api
        self._autosave_after_id = None
        self._current_email = None

        self._build(parent, get_email_credentials)

    def _build(self, tab_main, get_email_credentials):
        self.lbl_editing_status = ctk.CTkLabel(tab_main, text="⚙️ Редагування: (не вибрано)",
                                               font=ctk.CTkFont(size=20, weight="bold"), text_color="#1fa5ff")
        self.lbl_editing_status.pack(pady=(10, 5))

        main_container = ctk.CTkFrame(tab_main, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=10, pady=(5, 0))
        main_container.grid_columnconfigure(0, weight=6)
        main_container.grid_columnconfigure(1, weight=4)

        # ── Left side: fields + finances ──
        left_side = ctk.CTkFrame(main_container, fg_color="transparent")
        left_side.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        fields_card = ctk.CTkFrame(left_side, fg_color="#212121", corner_radius=10,
                                   border_width=1, border_color="#343638")
        fields_card.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(fields_card, text="📝 Основні дані",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15, anchor="w")

        inner_fields = ctk.CTkFrame(fields_card, fg_color="transparent")
        inner_fields.pack(fill="x", padx=10, pady=(0, 10))
        inner_fields.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(inner_fields, text="Головна пошта:", text_color="gray").grid(
            row=0, column=0, sticky="w", padx=5, pady=(5, 0))
        ctk.CTkLabel(inner_fields, text="Стара пошта:", text_color="gray").grid(
            row=0, column=1, sticky="w", padx=5, pady=(5, 0))

        frame_main_email, self.entry_main_email = create_entry_with_copy(
            inner_fields, self.copy_func, font=ctk.CTkFont(weight="bold"))
        frame_main_email.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))

        frame_old_email, self.entry_old_email = create_entry_with_copy(inner_fields, self.copy_func)
        frame_old_email.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 10))

        ctk.CTkLabel(inner_fields, text="Пароль:", text_color="gray").grid(
            row=2, column=0, sticky="w", padx=5, pady=(5, 0))
        ctk.CTkLabel(inner_fields, text="API Key:", text_color="gray").grid(
            row=2, column=1, sticky="w", padx=5, pady=(5, 0))

        frame_pass, self.entry_pass = create_entry_with_copy(inner_fields, self.copy_func)
        frame_pass.grid(row=3, column=0, sticky="ew", padx=5, pady=(0, 10))

        frame_api, self.entry_api = create_entry_with_copy(inner_fields, self.copy_func)
        self.btn_create_api = ctk.CTkButton(
            frame_api,
            text="Create API",
            width=90,
            fg_color="#1f538d",
            hover_color="#143a63",
            command=self._on_create_api,
        )
        self.btn_create_api.grid(row=0, column=2, padx=(5, 0))
        frame_api.grid(row=3, column=1, sticky="ew", padx=5, pady=(0, 10))

        ctk.CTkLabel(inner_fields, text="Secret Key (Термінал):", text_color="gray").grid(
            row=4, column=0, sticky="w", padx=5, pady=(5, 0))
        ctk.CTkLabel(inner_fields, text="Статус (Папка):", text_color="gray").grid(
            row=4, column=1, sticky="w", padx=5, pady=(5, 0))

        frame_secret, self.entry_secret = create_entry_with_copy(inner_fields, self.copy_func)
        frame_secret.grid(row=5, column=0, sticky="ew", padx=5, pady=(0, 10))

        self.status_var = ctk.StringVar(value=STATUSES[0])
        self.opt_status = ctk.CTkOptionMenu(inner_fields, values=STATUSES, variable=self.status_var,
                                            command=lambda _: self._schedule_autosave())
        self.opt_status.grid(row=5, column=1, sticky="ew", padx=5, pady=(0, 10))

        # ── Finances card ──
        finances_card = ctk.CTkFrame(left_side, fg_color="#212121", corner_radius=10,
                                     border_width=1, border_color="#343638")
        finances_card.pack(fill="x", pady=0)

        ctk.CTkLabel(finances_card, text="💰 Фінанси",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5), padx=15, anchor="w")

        inner_fin = ctk.CTkFrame(finances_card, fg_color="transparent")
        inner_fin.pack(fill="x", padx=10, pady=(0, 10))
        inner_fin.grid_columnconfigure((0, 1, 2), weight=1)
        inner_fin.grid_columnconfigure(3, weight=0)

        ctk.CTkLabel(inner_fin, text="Вкладено ($):", text_color="gray").grid(
            row=0, column=0, sticky="w", padx=5, pady=(5, 0))
        ctk.CTkLabel(inner_fin, text="Депозит ($):", text_color="gray").grid(
            row=0, column=1, sticky="w", padx=5, pady=(5, 0))
        ctk.CTkLabel(inner_fin, text="Баланс ($):", text_color="gray").grid(
            row=0, column=2, sticky="w", padx=5, pady=(5, 0))

        self.entry_invested = ctk.CTkEntry(inner_fin)
        self.entry_invested.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 10))

        self.entry_deposit = ctk.CTkEntry(inner_fin)
        self.entry_deposit.grid(row=1, column=1, sticky="ew", padx=5, pady=(0, 10))

        self.entry_balance = ctk.CTkEntry(inner_fin)
        self.entry_balance.grid(row=1, column=2, sticky="ew", padx=5, pady=(0, 10))

        self.lbl_profit = ctk.CTkLabel(inner_fin, text="Прибуток:\n$0.0",
                                       font=ctk.CTkFont(size=16, weight="bold"))
        self.lbl_profit.grid(row=0, column=3, rowspan=2, padx=15, pady=5)

        # ── Right side: 2FA + email codes ──
        right_side = ctk.CTkFrame(main_container, fg_color="transparent")
        right_side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        self.two_fa_widget = TwoFactorAuthWidget(
            right_side,
            self.copy_func,
            on_create_2fa=self.on_create_2fa,
        )
        self.two_fa_widget.pack(fill="x", pady=(0, 15))

        self.email_codes_widget = EmailCodesWidget(right_side, self.copy_func, get_email_credentials)
        self.email_codes_widget.pack(fill="both", expand=True)

        # ── Autosave bindings ──
        self._setup_autosave_bindings()

    def _setup_autosave_bindings(self):
        for entry in (self.entry_old_email, self.entry_pass, self.entry_api,
                      self.entry_secret, self.entry_invested, self.entry_deposit,
                      self.entry_balance, self.two_fa_widget.entry_secret):
            entry.bind("<KeyRelease>", lambda e: self._schedule_autosave())

    def display(self, account: Account):
        self._current_email = account.email
        self.lbl_editing_status.configure(text=f"⚙️ Редагування: {account.email}")

        self.entry_main_email.delete(0, 'end')
        self.entry_main_email.insert(0, account.email)
        self.entry_pass.delete(0, 'end')
        self.entry_pass.insert(0, account.password)
        self.entry_api.delete(0, 'end')
        self.entry_api.insert(0, account.api_key)
        self.entry_secret.delete(0, 'end')
        self.entry_secret.insert(0, account.secret_key)
        self.two_fa_widget.set_secret(account.two_fa_secret)
        self.entry_old_email.delete(0, 'end')
        self.entry_old_email.insert(0, account.old_email)
        self.status_var.set(account.status if account.status else STATUSES[0])

        self.entry_invested.delete(0, 'end')
        self.entry_invested.insert(0, str(account.invested))
        self.entry_deposit.delete(0, 'end')
        self.entry_deposit.insert(0, str(account.deposit))
        self.entry_balance.delete(0, 'end')
        self.entry_balance.insert(0, str(account.balance))

        color = "#00ff00" if account.net_profit >= 0 else "#ff4444"
        self.lbl_profit.configure(text=f"Прибуток:\n${account.net_profit}", text_color=color)

        for widget in self.email_codes_widget.codes_frame.winfo_children():
            widget.destroy()
        self.email_codes_widget.lbl_status.configure(
            text="Натисніть 'Оновити' або увімкніть Авто", text_color="gray")
        self.email_codes_widget.auto_var.set(False)
        self.email_codes_widget.last_found_code = None

    def collect(self) -> Account:
        """Read all fields into Account dataclass. Invalid floats fall back to 0."""
        try:
            inv = float(self.entry_invested.get() or 0)
        except ValueError:
            inv = 0.0
        try:
            dep = float(self.entry_deposit.get() or 0)
        except ValueError:
            dep = 0.0
        try:
            bal = float(self.entry_balance.get() or 0)
        except ValueError:
            bal = 0.0

        acc = Account(
            email=self._current_email or self.entry_main_email.get().strip(),
            password=self.entry_pass.get(),
            api_key=self.entry_api.get(),
            secret_key=self.entry_secret.get(),
            two_fa_secret=self.two_fa_widget.get_secret(),
            old_email=self.entry_old_email.get(),
            status=self.status_var.get(),
            invested=inv,
            deposit=dep,
            balance=bal,
        )
        acc.recalculate_profit()
        return acc

    def get_entered_email(self) -> str:
        return self.entry_main_email.get().strip()

    def set_entered_email(self, email: str):
        self.entry_main_email.delete(0, 'end')
        self.entry_main_email.insert(0, email)

    def update_profit(self, account: Account):
        color = "#00ff00" if account.net_profit >= 0 else "#ff4444"
        self.lbl_profit.configure(text=f"Прибуток:\n${account.net_profit}", text_color=color)

    def clear(self):
        self._current_email = None
        self.entry_main_email.delete(0, 'end')
        self.entry_pass.delete(0, 'end')
        self.entry_api.delete(0, 'end')
        self.entry_secret.delete(0, 'end')
        self.entry_old_email.delete(0, 'end')
        self.two_fa_widget.set_secret("")
        self.entry_invested.delete(0, 'end')
        self.entry_deposit.delete(0, 'end')
        self.entry_balance.delete(0, 'end')
        self.lbl_profit.configure(text="Прибуток:\n$0.0", text_color="white")
        self.lbl_editing_status.configure(text="⚙️ Редагування: (не вибрано)")

    # ── Autosave debounce ──

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
