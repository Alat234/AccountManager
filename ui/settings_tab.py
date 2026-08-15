import customtkinter as ctk

from services.mailbox_service import MailboxService
from storage.settings import SettingsManager


class SettingsTab:
    def __init__(
        self,
        parent,
        mailbox_service: MailboxService,
        settings: SettingsManager,
        show_status,
        on_ads_settings_saved=None,
    ):
        self.parent = parent
        self.mailbox_service = mailbox_service
        self.settings = settings
        self.show_status = show_status
        self.on_ads_settings_saved = on_ads_settings_saved

        self._build(parent)
        self.load_mailboxes()

    def _build(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        self.scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.scroll.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.scroll.grid_columnconfigure(0, weight=1)

        mail_card = self._card(self.scroll, "Пошти")
        mail_card.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 10))
        mail_card.grid_columnconfigure(0, weight=1)
        mail_card.grid_columnconfigure(1, weight=1)

        add_frame = ctk.CTkFrame(mail_card, fg_color="transparent")
        add_frame.grid(row=1, column=0, sticky="nsew", padx=(14, 8), pady=(0, 14))
        add_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(add_frame, text="IMAP сервер", text_color="gray").grid(row=0, column=0, sticky="w")
        self.entry_imap_server = ctk.CTkEntry(add_frame)
        self.entry_imap_server.insert(0, "imap.gmail.com")
        self.entry_imap_server.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(add_frame, text="Головна пошта", text_color="gray").grid(row=2, column=0, sticky="w")
        self.entry_main_email_input = ctk.CTkEntry(add_frame, placeholder_text="mail1@gmail.com")
        self.entry_main_email_input.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        ctk.CTkLabel(add_frame, text="Пароль додатку", text_color="gray").grid(row=4, column=0, sticky="w")
        self.entry_main_pass_input = ctk.CTkEntry(add_frame, show="*")
        self.entry_main_pass_input.grid(row=5, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkButton(
            add_frame,
            text="+ Додати пошту",
            fg_color="#218a43",
            hover_color="#16652f",
            command=self.add_mailbox,
        ).grid(row=6, column=0, sticky="ew")

        self.mailboxes_frame = ctk.CTkScrollableFrame(
            mail_card,
            label_text="Підключені пошти",
            height=190,
        )
        self.mailboxes_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 14), pady=(0, 14))

        ads_card = self._card(self.scroll, "AdsPower")
        ads_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        ads_card.grid_columnconfigure(1, weight=1)

        self._label(ads_card, "API Key", 1, 0)
        self.entry_ads_token = ctk.CTkEntry(ads_card, show="*")
        self.entry_ads_token.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        saved_ads = self.settings.get("adspower_api_key", "")
        if saved_ads:
            self.entry_ads_token.insert(0, saved_ads)

        self._label(ads_card, "Local API URL", 2, 0)
        self.entry_ads_base_url = ctk.CTkEntry(ads_card)
        self.entry_ads_base_url.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        self.entry_ads_base_url.insert(
            0,
            self.settings.get("adspower_base_url", "http://local.adspower.net:50401"),
        )

        ctk.CTkButton(
            ads_card,
            text="Зберегти AdsPower",
            command=self._save_ads_token,
            width=150,
        ).grid(row=1, column=2, rowspan=2, sticky="ns", padx=(8, 14), pady=6)

        icloud_card = self._card(self.scroll, "iCloud")
        icloud_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
        icloud_card.grid_columnconfigure(1, weight=1)

        self._label(icloud_card, "iCloud Profile ID", 1, 0)
        self.entry_icloud_profile_id = ctk.CTkEntry(icloud_card)
        self.entry_icloud_profile_id.grid(row=1, column=1, sticky="ew", padx=8, pady=(6, 14))
        saved_icloud_profile_id = self.settings.get("icloud_ads_profile_id", "")
        if saved_icloud_profile_id:
            self.entry_icloud_profile_id.insert(0, saved_icloud_profile_id)
        ctk.CTkButton(
            icloud_card,
            text="Зберегти",
            command=self._save_icloud_profile_id,
            width=120,
        ).grid(row=1, column=2, padx=(8, 14), pady=(6, 14))

        mexc_card = self._card(self.scroll, "MEXC")
        mexc_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 10))
        mexc_card.grid_columnconfigure(1, weight=1)

        self._label(mexc_card, "Referral Code", 1, 0)
        self.entry_mexc_referral = ctk.CTkEntry(mexc_card)
        self.entry_mexc_referral.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        saved_referral = self.settings.get("mexc_referral_code", "")
        if saved_referral:
            self.entry_mexc_referral.insert(0, saved_referral)

        self._label(mexc_card, "Default Password", 2, 0)
        self.entry_mexc_password = ctk.CTkEntry(mexc_card, show="*")
        self.entry_mexc_password.grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        saved_password = self.settings.get("mexc_default_password", "")
        if saved_password:
            self.entry_mexc_password.insert(0, saved_password)

        self._label(mexc_card, "Main API Key", 3, 0)
        self.entry_mexc_main_api_key = ctk.CTkEntry(mexc_card, show="*")
        self.entry_mexc_main_api_key.grid(row=3, column=1, sticky="ew", padx=8, pady=6)
        saved_main_api_key = self.settings.get("mexc_main_api_key", "")
        if saved_main_api_key:
            self.entry_mexc_main_api_key.insert(0, saved_main_api_key)

        self._label(mexc_card, "Main Secret Key", 4, 0)
        self.entry_mexc_main_secret_key = ctk.CTkEntry(mexc_card, show="*")
        self.entry_mexc_main_secret_key.grid(row=4, column=1, sticky="ew", padx=8, pady=6)
        saved_main_secret_key = self.settings.get("mexc_main_secret_key", "")
        if saved_main_secret_key:
            self.entry_mexc_main_secret_key.insert(0, saved_main_secret_key)

        self.lbl_mexc_pwd_error = ctk.CTkLabel(
            mexc_card,
            text="",
            text_color="red",
            font=ctk.CTkFont(size=11),
        )
        self.lbl_mexc_pwd_error.grid(row=5, column=1, sticky="w", padx=8, pady=(0, 10))

        ctk.CTkButton(
            mexc_card,
            text="Зберегти MEXC",
            command=self._save_mexc_settings,
            width=150,
        ).grid(row=1, column=2, rowspan=4, sticky="ns", padx=(8, 14), pady=6)

        tg_card = self._card(self.scroll, "Telegram Bot")
        tg_card.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 18))
        tg_card.grid_columnconfigure(1, weight=1)

        self._label(tg_card, "Bot Token", 1, 0)
        self.entry_tg_token = ctk.CTkEntry(tg_card, show="*")
        self.entry_tg_token.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        saved_tg = self.settings.get("telegram_bot_token", "")
        if saved_tg:
            self.entry_tg_token.insert(0, saved_tg)

        self._label(tg_card, "User ID", 2, 0)
        self.entry_tg_user_id = ctk.CTkEntry(tg_card, width=200)
        self.entry_tg_user_id.grid(row=2, column=1, sticky="w", padx=8, pady=(6, 14))
        saved_uid = self.settings.get("telegram_user_id", "")
        if saved_uid:
            self.entry_tg_user_id.insert(0, str(saved_uid))

        ctk.CTkButton(
            tg_card,
            text="Зберегти Telegram",
            command=self._save_tg_settings,
            width=150,
        ).grid(row=1, column=2, rowspan=2, sticky="ns", padx=(8, 14), pady=6)

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
            font=ctk.CTkFont(weight="bold", size=16),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 8))
        return card

    @staticmethod
    def _label(parent, text, row, column):
        ctk.CTkLabel(parent, text=text, text_color="gray").grid(
            row=row,
            column=column,
            sticky="w",
            padx=(14, 8),
            pady=6,
        )

    def _save_ads_token(self):
        token = self.entry_ads_token.get().strip()
        base_url = self._normalize_ads_base_url(self.entry_ads_base_url.get().strip())
        self.entry_ads_base_url.delete(0, "end")
        self.entry_ads_base_url.insert(0, base_url)
        self.settings.set("adspower_api_key", token)
        self.settings.set("adspower_base_url", base_url)
        if self.on_ads_settings_saved:
            self.on_ads_settings_saved(token, base_url)
        self.show_status("AdsPower налаштування збережено!", "green")

    def get_ads_token(self):
        return self.entry_ads_token.get().strip()

    @staticmethod
    def _normalize_ads_base_url(value: str) -> str:
        value = (value or "").strip().rstrip("/")
        if not value:
            return "http://local.adspower.net:50401"
        if value.isdigit():
            return f"http://127.0.0.1:{value}"
        if "://" not in value:
            return f"http://{value}"
        return value

    def _save_icloud_profile_id(self):
        profile_id = self.entry_icloud_profile_id.get().strip()
        self.settings.set("icloud_ads_profile_id", profile_id)
        self.show_status("iCloud Profile ID збережено!", "green")

    def _save_mexc_settings(self):
        referral_code = self.entry_mexc_referral.get().strip()
        password = self.entry_mexc_password.get().strip()
        main_api_key = self.entry_mexc_main_api_key.get().strip()
        main_secret_key = self.entry_mexc_main_secret_key.get().strip()

        if password:
            from utils.validators import PasswordValidator
            is_valid, error = PasswordValidator.validate(password)
            if not is_valid:
                self.lbl_mexc_pwd_error.configure(text=error)
                self.show_status(f"MEXC password is invalid: {error}", "red")
                return

        self.lbl_mexc_pwd_error.configure(text="")
        self.settings.set("mexc_referral_code", referral_code)
        self.settings.set("mexc_default_password", password)
        self.settings.set("mexc_main_api_key", main_api_key)
        self.settings.set("mexc_main_secret_key", main_secret_key)
        self.show_status("MEXC налаштування збережено!", "green")

    def _save_tg_settings(self):
        token = self.entry_tg_token.get().strip()
        user_id = self.entry_tg_user_id.get().strip()
        self.settings.set("telegram_bot_token", token)
        self.settings.set("telegram_user_id", user_id)
        self.show_status("Telegram налаштування збережено!", "green")

    def add_mailbox(self):
        server = self.entry_imap_server.get().strip()
        email = self.entry_main_email_input.get().strip()
        pwd = self.entry_main_pass_input.get().strip()
        if server and email and pwd:
            self.mailbox_service.add_mailbox(email, pwd, server)
            self.entry_main_email_input.delete(0, "end")
            self.entry_main_pass_input.delete(0, "end")
            self.load_mailboxes()
            self.show_status("Пошту підключено!", "green")
        else:
            self.show_status("Заповніть усі поля пошти!", "red")

    def load_mailboxes(self):
        for widget in self.mailboxes_frame.winfo_children():
            widget.destroy()

        mailboxes = self.mailbox_service.get_all_mailboxes()
        if not mailboxes:
            ctk.CTkLabel(
                self.mailboxes_frame,
                text="Пошт ще немає",
                text_color="gray",
            ).pack(padx=10, pady=12)
            return

        for mailbox in mailboxes:
            frame = ctk.CTkFrame(self.mailboxes_frame, fg_color="#2b2b2b", corner_radius=6)
            frame.pack(fill="x", pady=3, padx=5)
            info = ctk.CTkFrame(frame, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkLabel(
                info,
                text=mailbox.email,
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                info,
                text=mailbox.server,
                text_color="gray",
                font=ctk.CTkFont(size=11),
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkButton(
                frame,
                text="X",
                width=30,
                fg_color="#8b0000",
                hover_color="#5c0000",
                command=lambda email=mailbox.email: self.delete_mailbox(email),
            ).pack(side="right", padx=8, pady=8)

    def delete_mailbox(self, email):
        self.mailbox_service.delete_mailbox(email)
        self.load_mailboxes()
        self.show_status("Пошту видалено.", "green")
