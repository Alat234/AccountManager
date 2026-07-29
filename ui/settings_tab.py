import customtkinter as ctk

from services.mailbox_service import MailboxService
from storage.settings import SettingsManager


class SettingsTab:
    def __init__(self, parent, mailbox_service: MailboxService, settings: SettingsManager, show_status):
        self.parent = parent
        self.mailbox_service = mailbox_service
        self.settings = settings
        self.show_status = show_status

        self._build(parent)
        self.load_mailboxes()

    def _build(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)

        # ── Mailbox section ──
        set_frame = ctk.CTkFrame(tab)
        set_frame.grid(row=0, column=0, pady=(20, 10), padx=20, sticky="ew")

        ctk.CTkLabel(set_frame, text="Додавання Головних Пошт (куди йде переадресація)",
                     font=ctk.CTkFont(weight="bold", size=16)).pack(pady=(15, 5))

        form_frame = ctk.CTkFrame(set_frame, fg_color="transparent")
        form_frame.pack(pady=10)

        ctk.CTkLabel(form_frame, text="IMAP Сервер:").grid(row=0, column=0, padx=5, sticky="w")
        self.entry_imap_server = ctk.CTkEntry(form_frame, width=150)
        self.entry_imap_server.insert(0, "imap.gmail.com")
        self.entry_imap_server.grid(row=1, column=0, padx=5)

        ctk.CTkLabel(form_frame, text="Пошта (напр. mail1@gmail.com):").grid(row=0, column=1, padx=5, sticky="w")
        self.entry_main_email_input = ctk.CTkEntry(form_frame, width=200)
        self.entry_main_email_input.grid(row=1, column=1, padx=5)

        ctk.CTkLabel(form_frame, text="Пароль додатку:").grid(row=0, column=2, padx=5, sticky="w")
        self.entry_main_pass_input = ctk.CTkEntry(form_frame, width=200, show="*")
        self.entry_main_pass_input.grid(row=1, column=2, padx=5)

        ctk.CTkButton(form_frame, text="+ Додати пошту",
                      command=self.add_mailbox).grid(row=1, column=3, padx=15)

        # ── AdsPower section ──
        ads_frame = ctk.CTkFrame(tab)
        ads_frame.grid(row=1, column=0, pady=(0, 10), padx=20, sticky="ew")

        ctk.CTkLabel(ads_frame, text="AdsPower",
                     font=ctk.CTkFont(weight="bold", size=16)).pack(pady=(15, 5))

        ads_token_frame = ctk.CTkFrame(ads_frame, fg_color="transparent")
        ads_token_frame.pack(pady=(0, 10), padx=15, fill="x")

        ctk.CTkLabel(ads_token_frame, text="API Key:").pack(side="left", padx=(0, 10))
        self.entry_ads_token = ctk.CTkEntry(ads_token_frame, show="*", width=400)
        self.entry_ads_token.pack(side="left", fill="x", expand=True, padx=(0, 10))

        saved_ads = self.settings.get("adspower_api_key", "")
        if saved_ads:
            self.entry_ads_token.insert(0, saved_ads)

        ctk.CTkButton(ads_token_frame, text="Зберегти",
                      command=self._save_ads_token, width=100).pack(side="left")

        ads_url_frame = ctk.CTkFrame(ads_frame, fg_color="transparent")
        ads_url_frame.pack(pady=(0, 10), padx=15, fill="x")

        ctk.CTkLabel(ads_url_frame, text="Local API URL:").pack(side="left", padx=(0, 10))
        self.entry_ads_base_url = ctk.CTkEntry(ads_url_frame, width=400)
        self.entry_ads_base_url.pack(side="left", fill="x", expand=True, padx=(0, 10))

        saved_ads_base_url = self.settings.get("adspower_base_url", "http://local.adspower.net:50401")
        self.entry_ads_base_url.insert(0, saved_ads_base_url)

        icloud_frame = ctk.CTkFrame(ads_frame, fg_color="transparent")
        icloud_frame.pack(pady=(0, 15), padx=15, fill="x")

        ctk.CTkLabel(icloud_frame, text="iCloud Profile ID:").pack(side="left", padx=(0, 10))
        self.entry_icloud_profile_id = ctk.CTkEntry(icloud_frame, width=400)
        self.entry_icloud_profile_id.pack(side="left", fill="x", expand=True, padx=(0, 10))

        saved_icloud_profile_id = self.settings.get("icloud_ads_profile_id", "")
        if saved_icloud_profile_id:
            self.entry_icloud_profile_id.insert(0, saved_icloud_profile_id)

        ctk.CTkButton(icloud_frame, text="Зберегти",
                      command=self._save_icloud_profile_id, width=100).pack(side="left")

        # ── MEXC section ──
        mexc_frame = ctk.CTkFrame(tab)
        mexc_frame.grid(row=2, column=0, pady=(0, 10), padx=20, sticky="ew")

        ctk.CTkLabel(mexc_frame, text="MEXC",
                     font=ctk.CTkFont(weight="bold", size=16)).pack(pady=(15, 5))

        mexc_inner = ctk.CTkFrame(mexc_frame, fg_color="transparent")
        mexc_inner.pack(pady=(0, 15), padx=15, fill="x")

        ctk.CTkLabel(mexc_inner, text="Referral Code:").grid(row=0, column=0, padx=(0, 10), sticky="w")
        self.entry_mexc_referral = ctk.CTkEntry(mexc_inner, width=350)
        self.entry_mexc_referral.grid(row=0, column=1, padx=(0, 10), sticky="ew")

        saved_referral = self.settings.get("mexc_referral_code", "")
        if saved_referral:
            self.entry_mexc_referral.insert(0, saved_referral)

        ctk.CTkLabel(mexc_inner, text="Default Password:").grid(row=1, column=0, padx=(0, 10), pady=(5, 0), sticky="w")
        self.entry_mexc_password = ctk.CTkEntry(mexc_inner, show="*", width=350)
        self.entry_mexc_password.grid(row=1, column=1, padx=(0, 10), pady=(5, 0), sticky="ew")

        saved_password = self.settings.get("mexc_default_password", "")
        if saved_password:
            self.entry_mexc_password.insert(0, saved_password)

        self.lbl_mexc_pwd_error = ctk.CTkLabel(mexc_inner, text="", text_color="red", font=ctk.CTkFont(size=11))
        self.lbl_mexc_pwd_error.grid(row=2, column=1, padx=(0, 10), pady=(3, 0), sticky="w")

        ctk.CTkButton(mexc_inner, text="Зберегти",
                      command=self._save_mexc_settings, width=100).grid(row=0, column=2, rowspan=2)

        mexc_inner.grid_columnconfigure(1, weight=1)

        tg_frame = ctk.CTkFrame(tab)
        tg_frame.grid(row=3, column=0, pady=(0, 10), padx=20, sticky="ew")

        ctk.CTkLabel(tg_frame, text="Telegram Bot",
                     font=ctk.CTkFont(weight="bold", size=16)).pack(pady=(15, 5))

        tg_inner = ctk.CTkFrame(tg_frame, fg_color="transparent")
        tg_inner.pack(pady=(0, 15), padx=15, fill="x")

        ctk.CTkLabel(tg_inner, text="Bot Token:").grid(row=0, column=0, padx=(0, 10), sticky="w")
        self.entry_tg_token = ctk.CTkEntry(tg_inner, show="*", width=350)
        self.entry_tg_token.grid(row=0, column=1, padx=(0, 10), sticky="ew")

        saved_tg = self.settings.get("telegram_bot_token", "")
        if saved_tg:
            self.entry_tg_token.insert(0, saved_tg)

        ctk.CTkLabel(tg_inner, text="User ID:").grid(row=1, column=0, padx=(0, 10), pady=(5, 0), sticky="w")
        self.entry_tg_user_id = ctk.CTkEntry(tg_inner, width=200)
        self.entry_tg_user_id.grid(row=1, column=1, padx=(0, 10), pady=(5, 0), sticky="w")

        saved_uid = self.settings.get("telegram_user_id", "")
        if saved_uid:
            self.entry_tg_user_id.insert(0, str(saved_uid))

        ctk.CTkButton(tg_inner, text="Зберегти",
                      command=self._save_tg_settings, width=100).grid(row=0, column=2, rowspan=2)

        tg_inner.grid_columnconfigure(1, weight=1)

        # ── Mailboxes list ──
        self.mailboxes_frame = ctk.CTkScrollableFrame(tab, label_text="Список підключених пошт")
        self.mailboxes_frame.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="nsew")

    # ── Save callbacks ──

    def _save_ads_token(self):
        token = self.entry_ads_token.get().strip()
        base_url = self.entry_ads_base_url.get().strip().rstrip("/")
        self.settings.set("adspower_api_key", token)
        self.settings.set("adspower_base_url", base_url)
        self.show_status("AdsPower API key збережено!", "green")

    def get_ads_token(self):
        return self.entry_ads_token.get().strip()

    def _save_icloud_profile_id(self):
        profile_id = self.entry_icloud_profile_id.get().strip()
        self.settings.set("icloud_ads_profile_id", profile_id)
        self.show_status("iCloud Profile ID збережено!", "green")

    def _save_mexc_settings(self):
        referral_code = self.entry_mexc_referral.get().strip()
        password = self.entry_mexc_password.get().strip()

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
        self.show_status("MEXC settings saved!", "green")

    def _save_tg_settings(self):
        token = self.entry_tg_token.get().strip()
        user_id = self.entry_tg_user_id.get().strip()
        self.settings.set("telegram_bot_token", token)
        self.settings.set("telegram_user_id", user_id)
        self.show_status("Telegram налаштування збережено!", "green")

    # ── Mailbox management ──

    def add_mailbox(self):
        server = self.entry_imap_server.get().strip()
        email = self.entry_main_email_input.get().strip()
        pwd = self.entry_main_pass_input.get().strip()
        if server and email and pwd:
            self.mailbox_service.add_mailbox(email, pwd, server)
            self.entry_main_email_input.delete(0, 'end')
            self.entry_main_pass_input.delete(0, 'end')
            self.load_mailboxes()
            self.show_status("Пошту підключено!", "green")
        else:
            self.show_status("Заповніть всі поля!", "red")

    def load_mailboxes(self):
        for w in self.mailboxes_frame.winfo_children():
            w.destroy()
        for mb in self.mailbox_service.get_all_mailboxes():
            frame = ctk.CTkFrame(self.mailboxes_frame, fg_color="#2b2b2b")
            frame.pack(fill="x", pady=2, padx=5)
            ctk.CTkLabel(frame, text=f"{mb.email}  (Сервер: {mb.server})").pack(side="left", padx=10, pady=5)
            ctk.CTkButton(frame, text="X", width=30, fg_color="#8b0000", hover_color="#5c0000",
                          command=lambda e=mb.email: self.delete_mailbox(e)).pack(side="right", padx=10)

    def delete_mailbox(self, email):
        self.mailbox_service.delete_mailbox(email)
        self.load_mailboxes()
