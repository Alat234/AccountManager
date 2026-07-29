import os
import threading
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox

from models.account import ADS_CONFLICT, ADS_LINKED, ADS_ORPHANED, ADS_UNLINKED
from models.account import Account
from storage.constants import BASE_DIR, STATUSES, TAG_SHORT, FILTER_ALL
from storage.database import DatabaseManager
from storage.file_manager import FileManager
from storage.settings import SettingsManager
from services.account_service import AccountService
from services.mailbox_service import MailboxService
from services.captcha_service import CaptchaService
from services.task_service import TaskService
from services.profile_creation_service import ProfileCreationService
from clients.adspower import AdsPowerClient
from automation.runner import ScenarioRunner
from automation.scenarios.open_mexc import OpenMexcScenario
from automation.scenarios.register_mexc import RegisterMexcScenario
from automation.scenarios.link_mexc_2fa import LinkMexc2faScenario
from automation.scenarios.create_mexc_api import CreateMexcApiScenario
from services.mexc_email_service import MexcEmailCodeFetcher
from ui.account_list import AccountListPanel
from ui.details_tab import DetailsTab
from ui.notes_tab import NotesTab
from ui.table_tab import TableTab
from ui.settings_tab import SettingsTab
from ui.modals import open_delete_modal, BatchUploadModal, open_captcha_modal

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
ctk.deactivate_automatic_dpi_awareness()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Accounts Manager CRM PRO")
        self.geometry("1300x850")

        # ── Services ──
        self.db = DatabaseManager()
        self.fm = FileManager()
        self.account_service = AccountService(self.db, self.fm)
        self.mailbox_service = MailboxService(self.db)
        self.settings = SettingsManager()
        self.adspower = AdsPowerClient(
            self.settings.get("adspower_api_key", ""),
            base_url=self.settings.get("adspower_base_url", "") or None,
        )
        self.captcha_service = CaptchaService()
        self.task_service = TaskService(self.db)
        self.profile_creation = ProfileCreationService(self.account_service, self.adspower, self.settings)
        self.scenario_runner = ScenarioRunner(max_workers=2)
        self.captcha_service.register_listener(self._on_captcha_notification)

        # ── State ──
        self.current_account: Account | None = None
        self._captcha_modal = None

        # ── Build UI ──
        self._build_layout()

        # ── Sync with AdsPower + load data ──
        self._sync_adspower_on_startup()
        self._reload_account_list()
        self.table_tab.refresh()
        self._select_first_account()

        last_sync = self.settings.get("last_ads_sync", "")
        if last_sync:
            self.account_list.update_last_sync(last_sync)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-KeyPress>", self._handle_shortcuts)

    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Left panel ──
        left_frame = ctk.CTkFrame(self, width=450, corner_radius=0)
        left_frame.grid(row=0, column=0, sticky="nsew")

        self.account_list = AccountListPanel(
            left_frame,
            account_service=self.account_service,
            on_select=self.load_account,
            on_status_change=self._on_list_status_change,
        )
        self.account_list.set_create_command(self._create_account)
        self.account_list.set_icloud_command(self._create_account_icloud)
        self.account_list.set_sync_command(self._manual_sync_adspower)

        # ── Right panel ──
        right_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        right_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        right_frame.grid_columnconfigure(0, weight=1)
        right_frame.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(right_frame, command=self._on_tab_change)
        self.tabview.grid(row=0, column=0, sticky="nsew")

        tab_main = self.tabview.add("Деталі")
        tab_notes = self.tabview.add("Нотатки")
        tab_table = self.tabview.add("Таблиця (База)")
        tab_settings = self.tabview.add("⚙️ Налаштування")

        # ── Tabs ──
        self.details_tab = DetailsTab(
            tab_main,
            copy_func=self._copy_to_clipboard,
            get_email_credentials=self._get_email_credentials,
            on_autosave=self._autosave,
            on_create_2fa=self._run_link_mexc_2fa,
            on_create_api=self._run_create_mexc_api,
        )

        self.notes_tab = NotesTab(tab_notes, on_change=self._schedule_notes_autosave,
                                   on_remark_save=self._save_remark)

        self.table_tab = TableTab(
            tab_table,
            account_service=self.account_service,
            on_double_click=self._on_table_double_click,
        )

        self.settings_tab = SettingsTab(
            tab_settings,
            mailbox_service=self.mailbox_service,
            settings=self.settings,
            show_status=self._show_status,
        )

        # ── Bottom buttons ──
        self.btn_frame = ctk.CTkFrame(right_frame, fg_color="transparent")
        self.btn_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        ctk.CTkButton(self.btn_frame, text="📋 Завантажити файли",
                      command=self._open_batch_modal).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="📁 Відкрити папку",
                      command=self._open_folder).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="AdsPower",
                      command=self._launch_adspower).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="Unlink ADS", fg_color="#6a4c93",
                      hover_color="#4a3570",
                      command=self._unlink_adspower).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="Open MEXC",
                      command=self._run_open_mexc).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="Register MEXC", fg_color="#1f538d",
                      hover_color="#143a63", command=self._run_register_mexc).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="🗑 Видалити акаунт", fg_color="#8b0000",
                      hover_color="#5c0000", command=self._delete_account).pack(side="right", padx=5)
        ctk.CTkButton(self.btn_frame, text="💾 Зберегти зміни", fg_color="#b35b04",
                      hover_color="#d9710b", command=self._save_account).pack(side="right", padx=5)

        self.lbl_status = ctk.CTkLabel(right_frame, text="", font=ctk.CTkFont(size=12))
        self.lbl_status.grid(row=2, column=0)

    # ── Account loading ──

    def _select_first_account(self):
        email = self.account_service.get_first_email()
        if email:
            self.load_account(email)

    def load_account(self, email):
        self.details_tab.flush_autosave()
        account = self.account_service.get_account(email)
        if not account:
            return
        self.current_account = account
        self.details_tab.display(account)
        self.notes_tab.display(account)
        self.account_list.set_current(email)

    # ── Autosave ──

    def _autosave(self, silent=False):
        if not self.current_account:
            return
        account = self.details_tab.collect()
        account.text_notes = self.notes_tab.collect_notes()
        self._preserve_ads_fields(account, self.current_account)

        old_status = self.current_account.status
        status_changed = old_status != account.status

        try:
            self.account_service.save_account(account, old_status=old_status if status_changed else None)
        except Exception as e:
            self._show_status(f"Помилка збереження: {e}", "red")
            return

        self.current_account = account
        self.details_tab.update_profit(account)

        if status_changed:
            self.account_list.update_row_status(account.email, account.status)
            if self.account_list.get_filter() != FILTER_ALL:
                self.account_list.apply_filter()

        if not silent:
            self._show_status("💾 Авто-збережено", "#2fa572")

    def _schedule_notes_autosave(self):
        self.details_tab._schedule_autosave()

    # ── Account CRUD ──

    def _create_account(self):
        dialog = ctk.CTkInputDialog(text="Введіть Email нового акаунта:", title="Новий акаунт")
        email = dialog.get_input()
        if not email:
            return

        self._show_status("Створення акаунта...", "#2fa572")

        def worker():
            result = self.profile_creation.create_with_manual_email(email)
            self.after(0, lambda: self._on_profile_creation_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _create_account_icloud(self):
        self._show_status("Створення iCloud маски + AdsPower профілю...", "#2fa572")

        def worker():
            result = self.profile_creation.create_with_icloud()
            self.after(0, lambda: self._on_profile_creation_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _on_profile_creation_done(self, result):
        if result.success:
            self._reload_account_list()
            self.table_tab.refresh()
            if result.email:
                self.load_account(result.email)
        self._show_status(result.message, "green" if result.success else "red")

    def _save_account(self):
        if not self.current_account:
            self._show_status("Спочатку створіть або виберіть акаунт зліва!", "red")
            return
        self.details_tab._cancel_autosave()

        entered_email = self.details_tab.get_entered_email()
        if entered_email and entered_email != self.current_account.email:
            success = self.account_service.rename_account(self.current_account.email, entered_email)
            if success:
                self.current_account.email = entered_email
                self.details_tab._current_email = entered_email
                self.details_tab.lbl_editing_status.configure(text=f"⚙️ Редагування: {entered_email}")
                self._reload_account_list()
            else:
                self._show_status("Помилка перейменування!", "red")
                self.details_tab.set_entered_email(self.current_account.email)
                return

        self._autosave(silent=True)
        if self.tabview.get() == "Таблиця (База)":
            self.table_tab.refresh()
        self._show_status("Зміни успішно збережено!", "green")

    @staticmethod
    def _preserve_ads_fields(target: Account, source: Account) -> None:
        target.ads_profile_id = source.ads_profile_id
        target.ads_serial_number = source.ads_serial_number
        target.ads_remark = source.ads_remark
        target.ads_link_status = source.ads_link_status
        target.ads_manual_unlink = source.ads_manual_unlink
        target.ads_last_seen_at = source.ads_last_seen_at
        target.ads_profile_name = source.ads_profile_name
        target.ads_conflict_reason = source.ads_conflict_reason

    def _delete_account(self):
        if not self.current_account:
            return

        def on_confirm():
            self.details_tab._cancel_autosave()
            email = self.current_account.email
            self.account_service.delete_account(email)
            self.current_account = None
            self.details_tab.clear()
            self.notes_tab.clear()
            self.account_list.remove_row(email)
            if self.tabview.get() == "Таблиця (База)":
                self.table_tab.refresh()
            self._show_status("Акаунт успішно видалено!", "green")

        open_delete_modal(self, self.current_account.email, on_confirm)

    def _on_list_status_change(self, email, new_status):
        if self.current_account and email == self.current_account.email:
            self.details_tab.flush_autosave()

        try:
            old_status = self.account_service.change_status(email, new_status)
        except Exception as e:
            self._show_status(f"Не вдалося перемістити папку: {e}", "red")
            saved_status = self.account_service.get_status(email)
            if saved_status:
                self.account_list.update_row_status(email, saved_status)
            return

        if old_status is None:
            return

        if self.current_account and email == self.current_account.email:
            self.current_account.status = new_status
            self.details_tab.status_var.set(new_status)

        self.account_list.update_row_status(email, new_status)
        if self.account_list.get_filter() != FILTER_ALL:
            self.account_list.apply_filter()
        if self.tabview.get() == "Таблиця (База)":
            self.table_tab.refresh()
        self._show_status(f"Тег → {TAG_SHORT.get(new_status, new_status)}, папку переміщено", "#2fa572")

    # ── AdsPower ──

    def _reload_account_list(self):
        accounts_with_tags = self.db.get_all_accounts_with_tags()
        self.account_list.load_all(accounts_with_tags=accounts_with_tags)

    def _sync_adspower_on_startup(self):
        if not self.adspower.is_running():
            return
        try:
            stats = self.account_service.sync_with_adspower(self.adspower)
            self._save_sync_timestamp()
            if stats.get("created") or stats.get("linked") or stats.get("renamed") or stats.get("name_conflicts"):
                self._show_status(self._format_sync_message(stats), "green")
        except Exception:
            pass

    def _manual_sync_adspower(self):
        self._show_status("Синхронізація з AdsPower...", "#2fa572")
        self.account_list.btn_sync.configure(state="disabled")

        def worker():
            try:
                if not self.adspower.is_running():
                    self.after(0, lambda: self._show_status("AdsPower не запущений!", "red"))
                    return
                stats = self.account_service.sync_with_adspower(self.adspower)
                self._save_sync_timestamp()

                def on_done():
                    self._reload_account_list()
                    if self.current_account:
                        self.account_list.set_current(self.current_account.email)
                    self.table_tab.refresh()
                    parts = []
                    if stats.get("fetched"):
                        parts.append(f"{stats['fetched']} отримано з AdsPower")
                    if stats.get("created"):
                        parts.append(f"+{stats['created']} нових")
                    if stats.get("linked"):
                        parts.append(f"{stats['linked']} зв'язано")
                    if stats.get("renamed"):
                        parts.append(f"{stats['renamed']} перейменовано")
                    if stats.get("updated"):
                        parts.append(f"{stats['updated']} оновлено")
                    if stats.get("name_conflicts"):
                        parts.append(f"{stats['name_conflicts']} конфлікт назв")
                    if stats.get("orphaned"):
                        parts.append(f"{stats['orphaned']} старих без AdsPower")
                    msg = "Синхронізовано: " + ", ".join(parts) if parts else "Вже актуально"
                    self._show_status(msg, "green")

                self.after(0, on_done)
            except Exception as e:
                self.after(0, lambda: self._show_status(f"Помилка синхронізації: {e}", "red"))
            finally:
                self.after(0, lambda: self.account_list.btn_sync.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _format_sync_message(self, stats: dict) -> str:
        parts = []
        if stats.get("fetched"):
            parts.append(f"{stats['fetched']} отримано")
        if stats.get("created"):
            parts.append(f"+{stats['created']} нових")
        if stats.get("linked"):
            parts.append(f"{stats['linked']} зв'язано")
        if stats.get("renamed"):
            parts.append(f"{stats['renamed']} перейменовано")
        if stats.get("name_conflicts"):
            parts.append(f"{stats['name_conflicts']} конфлікт назв")
        if stats.get("orphaned"):
            parts.append(f"{stats['orphaned']} старих без AdsPower")
        return "Синхронізовано: " + ", ".join(parts) if parts else "Вже актуально"

    def _save_sync_timestamp(self):
        from datetime import datetime
        ts = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.settings.set("last_ads_sync", ts)
        self.after(0, lambda: self.account_list.update_last_sync(ts))

    def _save_remark(self, email, remark):
        self._show_status("Збереження remark...", "#2fa572")

        def worker():
            try:
                self.account_service.update_remark(email, remark, self.adspower)
                self.after(0, lambda: self._show_status("Remark збережено!", "green"))
            except Exception as e:
                self.after(0, lambda: self._show_status(f"Помилка: {e}", "red"))

        threading.Thread(target=worker, daemon=True).start()

    def _require_adspower_account(self, *, require_running: bool = True) -> Account | None:
        if not self.current_account:
            self._show_status("Select an account first!", "red")
            return None
        if not self.current_account.ads_profile_id:
            self._show_status("Account is not linked to an AdsPower profile!", "red")
            return None
        if self.current_account.ads_link_status != ADS_LINKED:
            status_labels = {
                ADS_UNLINKED: "unlinked",
                ADS_ORPHANED: "orphaned",
                ADS_CONFLICT: "conflict",
            }
            label = status_labels.get(self.current_account.ads_link_status, self.current_account.ads_link_status)
            self._show_status(f"AdsPower profile is not active for this account: {label}", "red")
            return None
        if require_running and not self.adspower.is_running():
            self._show_status("AdsPower is not running!", "red")
            return None
        return self.current_account

    def _launch_adspower(self):
        account = self._require_adspower_account(require_running=False)
        if not account:
            return

        profile_id = account.ads_profile_id
        self._show_status(f"Запускаю AdsPower профіль...", "#2fa572")

        def worker():
            if not self.adspower.is_running():
                self.after(0, lambda: self._show_status("AdsPower не запущений!", "red"))
                return

            if self.adspower.is_browser_active(profile_id):
                self.after(0, lambda: self._show_status("Профіль вже відкритий!", "#2fa572"))
                return

            conn = self.adspower.start_browser(profile_id)
            if conn:
                self.after(0, lambda: self._show_status("AdsPower профіль запущено!", "green"))
            else:
                self.after(0, lambda: self._show_status("Не вдалося запустити профіль!", "red"))

        threading.Thread(target=worker, daemon=True).start()

    def _unlink_adspower(self):
        if not self.current_account:
            self._show_status("Select an account first!", "red")
            return
        if not self.current_account.ads_profile_id:
            self._show_status("Account has no AdsPower profile link.", "red")
            return
        confirmed = messagebox.askyesno(
            "Unlink AdsPower",
            "Unlink this local account from its AdsPower profile?\n\n"
            "The AdsPower profile will not be deleted. The profile ID will be kept in history and sync will not relink it automatically.",
            parent=self,
        )
        if not confirmed:
            return
        email = self.current_account.email
        if self.account_service.unlink_adspower_profile(email, manual=True, note="Manual unlink from desktop UI"):
            self.current_account = self.account_service.get_account(email)
            self._reload_account_list()
            self.account_list.set_current(email)
            self._show_status("AdsPower profile unlinked locally.", "green")
        else:
            self._show_status("Failed to unlink AdsPower profile.", "red")

    # ── Automation ──

    def _submit_scenario_task(self, scenario_type: str, scenario, on_complete, status_message: str):
        scenario_account = getattr(scenario, "account", None)
        account_email = getattr(scenario_account, "email", "")
        task = self.task_service.create_task(account_email, scenario_type)
        self.task_service.start_task(task.id)
        scenario.task_id = task.id
        self.scenario_runner.submit(task.id, scenario, on_complete=on_complete)
        self._show_status(status_message, "#2fa572")
        return task

    def _run_open_mexc(self):
        account = self._require_adspower_account()
        if not account:
            return

        scenario = OpenMexcScenario(self.adspower, account, self.captcha_service)
        self._submit_scenario_task(
            "open_mexc",
            scenario,
            self._on_scenario_complete,
            "Open MEXC scenario started...",
        )

    def _run_register_mexc(self):
        account = self._require_adspower_account()
        if not account:
            return

        self.details_tab.flush_autosave()

        if account.password:
            confirmed = messagebox.askyesno(
                "MEXC registration",
                "This account already has a saved password. It is probably already registered.\n\n"
                "Continue registration anyway?",
                parent=self,
            )
            if not confirmed:
                return

        referral_code = self.settings.get("mexc_referral_code", "").strip()
        if not referral_code:
            self._show_status("Set MEXC referral code in Settings first!", "red")
            return

        default_password = self.settings.get("mexc_default_password", "").strip()
        if not default_password:
            self._show_status("Set MEXC default password in Settings first!", "red")
            return

        from utils.validators import PasswordValidator
        is_valid, error = PasswordValidator.validate(default_password)
        if not is_valid:
            self._show_status(f"MEXC password is invalid: {error}", "red")
            return

        mailboxes_raw, _ = self._get_email_credentials()
        if not mailboxes_raw:
            self._show_status("Add mailbox credentials in Settings first!", "red")
            return

        email_fetcher = MexcEmailCodeFetcher(mailboxes_raw)

        scenario = RegisterMexcScenario(
            adspower=self.adspower,
            account=account,
            captcha_service=self.captcha_service,
            referral_code=referral_code,
            default_password=default_password,
            email_fetcher=email_fetcher,
            on_captcha_detected=lambda email: self.after(0, lambda: self._show_captcha_modal(email)),
        )
        self._submit_scenario_task(
            "register_mexc",
            scenario,
            self._on_register_complete,
            "MEXC registration started...",
        )

    def _run_link_mexc_2fa(self, after_success=None):
        account = self._require_adspower_account()
        if not account:
            return

        self.details_tab.flush_autosave()

        if not account.password:
            self._show_status("Save the MEXC account password first!", "red")
            return

        if account.two_fa_secret:
            confirmed = messagebox.askyesno(
                "MEXC 2FA",
                "This account already has a saved 2FA secret.\n\n"
                "Overwrite it and link 2FA again?",
                parent=self,
            )
            if not confirmed:
                return

        mailboxes_raw, _ = self._get_email_credentials()
        if not mailboxes_raw:
            self._show_status("Add mailbox credentials in Settings first!", "red")
            return

        email_fetcher = MexcEmailCodeFetcher(mailboxes_raw)

        scenario = LinkMexc2faScenario(
            adspower=self.adspower,
            account=account,
            captcha_service=self.captcha_service,
            email_fetcher=email_fetcher,
            on_captcha_detected=lambda email: self.after(0, lambda: self._show_captcha_modal(email)),
            on_email_timeout=self._ask_wait_more_for_email_code,
            on_secret_found=self._save_link_mexc_2fa_secret_early,
        )
        on_complete = self._on_link_2fa_complete
        if after_success:
            on_complete = lambda task_id, result: self._on_link_2fa_complete(
                task_id,
                result,
                after_success=after_success,
            )
        self._submit_scenario_task(
            "link_mexc_2fa",
            scenario,
            on_complete,
            "MEXC 2FA linking started...",
        )

    def _run_create_mexc_api(self, *, skip_existing_prompt: bool = False):
        account = self._require_adspower_account()
        if not account:
            return

        self.details_tab.flush_autosave()

        if not account.password:
            self._show_status("Save the MEXC account password first!", "red")
            return

        if (account.api_key or account.secret_key) and not skip_existing_prompt:
            confirmed = messagebox.askyesno(
                "MEXC API",
                "This account already has saved API credentials.\n\n"
                "Create a new API key and overwrite the saved values?",
                parent=self,
            )
            if not confirmed:
                return

        mailboxes_raw, _ = self._get_email_credentials()
        if not mailboxes_raw:
            self._show_status("Add mailbox credentials in Settings first!", "red")
            return

        if not account.two_fa_secret:
            confirmed = messagebox.askyesno(
                "MEXC API",
                "This account has no saved 2FA secret.\n\n"
                "Link 2FA now and continue API creation automatically?",
                parent=self,
            )
            if not confirmed:
                self._show_status("MEXC API creation stopped: 2FA is required.", "red")
                return
            self._run_link_mexc_2fa(
                after_success=lambda: self._run_create_mexc_api(skip_existing_prompt=True)
            )
            return

        email_fetcher = MexcEmailCodeFetcher(mailboxes_raw)
        scenario = CreateMexcApiScenario(
            adspower=self.adspower,
            account=account,
            captcha_service=self.captcha_service,
            email_fetcher=email_fetcher,
            on_captcha_detected=lambda email: self.after(0, lambda: self._show_captcha_modal(email)),
            on_email_timeout=self._ask_wait_more_for_email_code,
        )
        self._submit_scenario_task(
            "create_mexc_api",
            scenario,
            self._on_create_api_complete,
            "MEXC API creation started...",
        )

    def _on_scenario_complete(self, task_id: str, result):
        self.task_service.complete_task(task_id, result)
        color = "green" if result.success else "red"
        self.after(0, lambda: self._show_status(result.message, color))

    def _show_captcha_modal(self, account_email: str):
        if self._captcha_modal is not None:
            try:
                self._captcha_modal.destroy()
            except Exception:
                pass
        self._captcha_modal = open_captcha_modal(self, account_email)

    def _ask_wait_more_for_email_code(self, account_email: str) -> bool:
        result = {"wait_more": False}

        def ask():
            result["wait_more"] = messagebox.askyesno(
                "MEXC email code",
                f"No MEXC verification code arrived for {account_email} within 180 seconds.\n\n"
                "Wait another 180 seconds?",
                parent=self,
            )
            event.set()

        event = threading.Event()
        self.after(0, ask)
        event.wait()
        return result["wait_more"]

    def _save_link_mexc_2fa_secret_early(self, account_email: str, two_fa_secret: str) -> None:
        done = threading.Event()

        def save():
            try:
                account = self.account_service.get_account(account_email)
                if account:
                    account.two_fa_secret = two_fa_secret
                    self.account_service.save_account(account)
                    if self.current_account and self.current_account.email == account_email:
                        self.current_account = account
                        self.details_tab.two_fa_widget.set_secret(two_fa_secret)
                    self._show_status("MEXC 2FA secret saved before verification...", "#2fa572")
            finally:
                done.set()

        self.after(0, save)
        done.wait()

    def _on_register_complete(self, task_id: str, result):
        self.task_service.complete_task(task_id, result)

        def update_ui():
            if self._captcha_modal is not None:
                try:
                    self._captcha_modal.destroy()
                except Exception:
                    pass
                self._captcha_modal = None

            if result.success:
                account_email = result.data.get("account_email", "")
                password = result.data.get("password", "")
                if account_email and password:
                    account = self.account_service.get_account(account_email)
                    if account:
                        account.password = password
                        self.account_service.save_account(account)
                        if self.current_account and self.current_account.email == account_email:
                            self.current_account = account
                            self.details_tab.entry_pass.delete(0, 'end')
                            self.details_tab.entry_pass.insert(0, password)
                self._show_status(result.message, "green")
            else:
                self._show_status(result.message, "red")

        self.after(0, update_ui)

    def _on_link_2fa_complete(self, task_id: str, result, after_success=None):
        self.task_service.complete_task(task_id, result)

        def update_ui():
            if self._captcha_modal is not None:
                try:
                    self._captcha_modal.destroy()
                except Exception:
                    pass
                self._captcha_modal = None

            if result.success:
                account_email = result.data.get("account_email", "")
                two_fa_secret = result.data.get("two_fa_secret", "")
                if account_email and two_fa_secret:
                    account = self.account_service.get_account(account_email)
                    if account:
                        account.two_fa_secret = two_fa_secret
                        self.account_service.save_account(account)
                        if self.current_account and self.current_account.email == account_email:
                            self.current_account = account
                            self.details_tab.two_fa_widget.set_secret(two_fa_secret)
                self._show_status(result.message, "green")
                if after_success:
                    self.after(100, after_success)
            else:
                self._show_status(result.message, "red")

        self.after(0, update_ui)

    def _on_create_api_complete(self, task_id: str, result):
        self.task_service.complete_task(task_id, result)

        def update_ui():
            if self._captcha_modal is not None:
                try:
                    self._captcha_modal.destroy()
                except Exception:
                    pass
                self._captcha_modal = None

            if result.success:
                account_email = result.data.get("account_email", "")
                api_key = result.data.get("api_key", "")
                secret_key = result.data.get("secret_key", "")
                if account_email and api_key and secret_key:
                    account = self.account_service.get_account(account_email)
                    if account:
                        account.api_key = api_key
                        account.secret_key = secret_key
                        self.account_service.save_account(account)
                        if self.current_account and self.current_account.email == account_email:
                            self.current_account = account
                            self.details_tab.entry_api.delete(0, 'end')
                            self.details_tab.entry_api.insert(0, api_key)
                            self.details_tab.entry_secret.delete(0, 'end')
                            self.details_tab.entry_secret.insert(0, secret_key)
                self._show_status(result.message, "green")
            else:
                self._show_status(result.message, "red")

        self.after(0, update_ui)

    def _on_captcha_notification(self, notification):
        msg = f"CAPTCHA: {notification.account_email} — перейдіть в браузер!"
        self.after(0, lambda: self._show_status(msg, "#ff9800"))

    # ── Tab management ──

    def _on_tab_change(self):
        tab = self.tabview.get()
        if tab in ("Таблиця (База)", "⚙️ Налаштування"):
            self.btn_frame.grid_remove()
            if tab == "Таблиця (База)":
                self.table_tab.refresh()
        else:
            self.btn_frame.grid()

    def _on_table_double_click(self, email):
        self.load_account(email)
        self.tabview.set("Деталі")

    # ── File operations ──

    def _open_batch_modal(self):
        if not self.current_account:
            self._show_status("Спочатку виберіть акаунт зі списку!", "red")
            return
        self.details_tab.flush_autosave()
        acc_dir = self.account_service.get_account_dir(self.current_account.email)
        if acc_dir:
            BatchUploadModal(self, self.current_account.email, acc_dir,
                             lambda count: self._show_status(f"Успішно збережено {count} файлів!", "green"))

    def _open_folder(self):
        if not self.current_account:
            return
        self.details_tab.flush_autosave()
        acc_dir = self.account_service.get_account_dir(self.current_account.email)
        if acc_dir and acc_dir.exists():
            os.startfile(acc_dir)
        else:
            self._show_status("Папку акаунта не знайдено!", "red")

    # ── Utilities ──

    def _copy_to_clipboard(self, text):
        if not text:
            self._show_status("Поле порожнє!", "red")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self._show_status("✅ Скопійовано!", "green")

    def _get_email_credentials(self):
        target = self.current_account.email if self.current_account else ""
        mailboxes = self.db.get_mailboxes()
        clean_mailboxes = [(m[0], m[1].replace(" ", ""), m[2]) for m in mailboxes]
        return clean_mailboxes, target

    def _show_status(self, text, color="white"):
        self.lbl_status.configure(text=text, text_color=color)
        self.after(3000, lambda: self.lbl_status.configure(text=""))

    def _handle_shortcuts(self, event):
        focused = self.focus_get()
        is_text_widget = isinstance(focused, (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text))
        keysym_lower = getattr(event, 'keysym', '').lower()
        if event.keycode == 86:
            if is_text_widget:
                if keysym_lower != 'v':
                    focused.event_generate("<<Paste>>")
                    return "break"
            else:
                if self.tabview.get() in ["Деталі", "Нотатки"]:
                    self._open_batch_modal()
                    return "break"
        elif event.keycode == 67:
            if is_text_widget and keysym_lower != 'c':
                focused.event_generate("<<Copy>>")
                return "break"
        elif event.keycode == 88:
            if is_text_widget and keysym_lower != 'x':
                focused.event_generate("<<Cut>>")
                return "break"
        elif event.keycode == 65:
            if is_text_widget and keysym_lower != 'a':
                if isinstance(focused, (ctk.CTkEntry, tk.Entry)):
                    focused.select_range(0, 'end')
                elif isinstance(focused, (ctk.CTkTextbox, tk.Text)):
                    focused.tag_add("sel", "1.0", "end")
                return "break"

    def _on_close(self):
        self.details_tab.flush_autosave()
        self.scenario_runner.shutdown()
        self.destroy()
