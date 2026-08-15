import os
import json
import threading
import uuid
import time
from datetime import datetime
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
from services.operation_event_service import OperationEventService
from services.task_service import TaskService
from services.profile_creation_service import ProfileCreationService
from clients.adspower import AdsPowerClient
from clients.mexc_api import MexcApiClient
from automation.runner import ScenarioRunner
from automation.progress import format_progress_step
from automation.recovery import (
    IssueType,
    ManualAssistAction,
    ManualAssistResult,
    PageState,
    ScenarioErrorClassifier,
    clean_error_message,
)
from automation.scenarios.open_mexc import OpenMexcScenario
from automation.scenarios.register_mexc import RegisterMexcScenario
from automation.scenarios.link_mexc_2fa import LinkMexc2faScenario
from automation.scenarios.create_mexc_api import CreateMexcApiScenario
from automation.scenarios.mexc_deposit_screenshot import MexcDepositScreenshotScenario
from automation.scenarios.mexc_state import MexcPageStateAnalyzer
from services.mexc_email_service import MexcEmailCodeFetcher
from ui.activity_log import ActivityLogPanel
from ui.account_list import AccountListPanel, VIEW_ARCHIVE
from ui.details_tab import DetailsTab
from ui.settings_tab import SettingsTab
from ui.modals import open_delete_modal, BatchUploadModal, open_captcha_modal

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
ctk.deactivate_automatic_dpi_awareness()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Accounts Manager CRM PRO")
        self.geometry("1500x900")

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
        self.event_service = OperationEventService(self.db, keep_per_account=1000)
        self.task_service = TaskService(self.db, self.event_service)
        self.profile_creation = ProfileCreationService(self.account_service, self.adspower, self.settings)
        self.scenario_runner = ScenarioRunner(max_workers=2)
        self.captcha_service.register_listener(self._on_captcha_notification)
        self.event_service.register_listener(self._on_operation_event)

        # ── State ──
        self.current_account: Account | None = None
        self._account_workspaces = {}
        self._workspace_by_tab = {}
        self._account_tab_order = []
        self._account_tab_frames = {}
        self._active_account_tab = ""
        self._pending_workspaces = {}
        self._running_accounts = set()
        self._task_scenarios = {}
        self.error_classifier = ScenarioErrorClassifier()
        self.mexc_state_analyzer = MexcPageStateAnalyzer()
        self._captcha_modal = None
        self._notification_toast = None
        self._notification_toast_after_id = None
        self._recent_notification_alerts = {}

        # ── Build UI ──
        self._build_layout()

        # ── Sync with AdsPower + load data ──
        self._sync_adspower_on_startup()
        self._reload_account_list()
        self._select_first_account()

        last_sync = self.settings.get("last_ads_sync", "")
        if last_sync:
            self.account_list.update_last_sync(last_sync)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-KeyPress>", self._handle_shortcuts)

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self, command=self._on_tab_change)
        self.tabview.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)

        tab_accounts = self.tabview.add("Акаунти")
        tab_account = self.tabview.add("Акаунт")
        tab_settings = self.tabview.add("Налаштування")

        # ── Full-screen account list ──
        tab_accounts.grid_columnconfigure(0, weight=1)

        self.account_list = AccountListPanel(
            tab_accounts,
            account_service=self.account_service,
            on_select=self.load_account,
            on_status_change=self._on_list_status_change,
            on_copy_email=self._copy_to_clipboard,
            on_view_change=self._on_account_list_view_change,
        )
        self.account_list.set_create_command(self._create_account)
        self.account_list.set_icloud_command(self._create_account_icloud)
        self.account_list.set_sync_command(self._manual_sync_adspower)

        # Multi-account workspace: each opened account gets an inner tab.
        tab_account.grid_columnconfigure(0, weight=1)
        tab_account.grid_rowconfigure(1, weight=1)

        self.account_tab_bar = ctk.CTkScrollableFrame(
            tab_account,
            height=46,
            orientation="horizontal",
            fg_color="#111316",
            corner_radius=8,
            label_text="",
        )
        self.account_tab_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))

        self.account_tabs_container = ctk.CTkFrame(tab_account, fg_color="transparent")
        self.account_tabs_container.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
        self.account_tabs_container.grid_columnconfigure(0, weight=1)
        self.account_tabs_container.grid_rowconfigure(0, weight=1)
        self.lbl_account_tabs_status = ctk.CTkLabel(
            tab_account,
            text="Open accounts from the account list. Each profile gets its own tab.",
            text_color="#9aa4ad",
            anchor="w",
        )
        self.lbl_account_tabs_status.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        self._render_account_tab_bar()
        self.details_tab = None
        self.activity_log = None
        self.lbl_status = self.lbl_account_tabs_status

        # ── Settings ──
        tab_settings.grid_columnconfigure(0, weight=1)
        tab_settings.grid_rowconfigure(0, weight=1)
        self.settings_tab = SettingsTab(
            tab_settings,
            mailbox_service=self.mailbox_service,
            settings=self.settings,
            show_status=self._show_status,
            on_ads_settings_saved=self._apply_adspower_settings,
        )

        self.tabview.set("Акаунти")

    @staticmethod
    def _action_group(parent, title, column):
        group = ctk.CTkFrame(parent, fg_color="#17191c", corner_radius=8)
        group.grid(row=0, column=column, sticky="ew", padx=5)
        ctk.CTkLabel(
            group,
            text=title,
            text_color="#9aa4ad",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(6, 2))
        buttons = ctk.CTkFrame(group, fg_color="transparent")
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        return buttons

    def _workspace_title(self, account: Account) -> str:
        serial = f"#{account.ads_serial_number}" if account.ads_serial_number else "local"
        email = account.email
        if len(email) > 30:
            name, _, domain = email.partition("@")
            email = f"{name[:12]}...@{domain}" if domain else f"{email[:27]}..."
        base = f"{serial} {email}"
        title = base
        counter = 2
        while title in self._workspace_by_tab and self._workspace_by_tab[title] != account.email:
            title = f"{base} ({counter})"
            counter += 1
        return title

    def _add_account_tab_frame(self, tab_name: str):
        frame = ctk.CTkFrame(self.account_tabs_container, corner_radius=0, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self._account_tab_frames[tab_name] = frame
        if tab_name not in self._account_tab_order:
            self._account_tab_order.append(tab_name)
        self._set_account_tab(tab_name)
        self._render_account_tab_bar()
        return frame

    def _set_account_tab(self, tab_name: str) -> None:
        frame = self._account_tab_frames.get(tab_name)
        if not frame:
            return
        for name, tab_frame in self._account_tab_frames.items():
            if name == tab_name:
                tab_frame.grid(row=0, column=0, sticky="nsew")
            else:
                tab_frame.grid_forget()
        self._active_account_tab = tab_name
        self._on_account_tab_change()
        self._render_account_tab_bar()

    def _get_account_tab(self) -> str:
        return self._active_account_tab

    def _delete_account_tab(self, tab_name: str) -> None:
        frame = self._account_tab_frames.pop(tab_name, None)
        if frame:
            frame.destroy()
        if tab_name in self._account_tab_order:
            self._account_tab_order.remove(tab_name)
        if self._active_account_tab == tab_name:
            self._active_account_tab = ""
        self._render_account_tab_bar()

    def _render_account_tab_bar(self) -> None:
        if not hasattr(self, "account_tab_bar"):
            return
        for child in self.account_tab_bar.winfo_children():
            child.destroy()

        for tab_name in self._account_tab_order:
            email = self._workspace_by_tab.get(tab_name, "")
            workspace = self._account_workspaces.get(email) if email else None
            pending_key = self._pending_key_for_tab(tab_name)
            is_active = tab_name == self._active_account_tab
            fg_color = "#1b2d3d" if is_active else "#17191c"
            hover_color = "#24384d"
            tab = ctk.CTkFrame(self.account_tab_bar, fg_color=fg_color, corner_radius=6)
            tab.pack(side="left", padx=(4, 2), pady=4)

            if workspace:
                account = workspace["account"]
                serial = f"#{account.ads_serial_number}" if account.ads_serial_number else "local"
                title = self._truncate_middle(account.email, 28)
                close_cmd = lambda name=tab_name: self._close_account_tab_by_name(name)
            else:
                serial = "+"
                title = self._truncate_middle(tab_name, 30)
                close_cmd = lambda key=pending_key: self._close_pending_workspace(key) if key else None

            ctk.CTkButton(
                tab,
                text=serial,
                width=52,
                height=28,
                fg_color="transparent",
                hover_color=hover_color,
                text_color="#7CFFB2",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda name=tab_name: self._set_account_tab(name),
            ).pack(side="left", padx=(6, 0), pady=5)
            ctk.CTkButton(
                tab,
                text=title,
                width=170,
                height=28,
                fg_color="transparent",
                hover_color=hover_color,
                anchor="w",
                command=lambda name=tab_name: self._set_account_tab(name),
            ).pack(side="left", padx=(0, 2), pady=5)
            ctk.CTkButton(
                tab,
                text="x",
                width=28,
                height=28,
                fg_color="transparent",
                hover_color="#4a2525",
                text_color="#c9d1d9",
                command=close_cmd,
            ).pack(side="left", padx=(0, 5), pady=5)

        ctk.CTkButton(
            self.account_tab_bar,
            text="+",
            width=36,
            height=30,
            fg_color="#1f538d",
            hover_color="#143a63",
            font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: self.tabview.set("Акаунти"),
        ).pack(side="left", padx=(5, 8), pady=4)

    def _pending_key_for_tab(self, tab_name: str) -> str | None:
        for key, workspace in self._pending_workspaces.items():
            if workspace.get("tab_name") == tab_name:
                return key
        return None

    def _close_account_tab_by_name(self, tab_name: str) -> None:
        current_tab = self._get_account_tab()
        self._set_account_tab(tab_name)
        self._close_current_account_tab()
        if current_tab and current_tab in self._account_tab_frames:
            self._set_account_tab(current_tab)

    @staticmethod
    def _truncate_middle(text: str, max_len: int) -> str:
        text = str(text or "")
        if len(text) <= max_len:
            return text
        keep = max_len - 3
        left = max(1, keep // 2)
        right = max(1, keep - left)
        return f"{text[:left]}...{text[-right:]}"

    def _create_account_workspace(self, account: Account):
        tab_name = self._workspace_title(account)
        tab = self._add_account_tab_frame(tab_name)
        tab.grid_columnconfigure(0, weight=2)
        tab.grid_columnconfigure(1, weight=5)
        tab.grid_rowconfigure(0, weight=1)

        log_frame = ctk.CTkFrame(tab, fg_color="transparent")
        log_frame.grid(row=0, column=0, sticky="nsew", padx=(8, 12), pady=8)
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        activity_log = ActivityLogPanel(log_frame)
        activity_log.grid(row=0, column=0, sticky="nsew")
        for event in reversed(self.event_service.recent_for_account(account.email, limit=80)):
            activity_log.add(event.message, event.level)

        account_workspace = ctk.CTkFrame(tab, corner_radius=0, fg_color="transparent")
        account_workspace.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        account_workspace.grid_columnconfigure(0, weight=1)
        account_workspace.grid_rowconfigure(0, weight=1)

        details_tab = DetailsTab(
            account_workspace,
            copy_func=self._copy_to_clipboard,
            get_email_credentials=self._get_email_credentials,
            on_autosave=self._autosave,
            on_create_2fa=self._run_link_mexc_2fa,
            on_create_api=self._run_create_mexc_api,
            on_read_latest_deposit=self._read_latest_mexc_deposit,
            on_find_deposit_screenshot=self._run_find_deposit_screenshot,
            on_remark_save=self._save_remark,
        )

        btn_frame = ctk.CTkFrame(account_workspace, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        files_group = self._action_group(btn_frame, "Файли", 0)
        ctk.CTkButton(files_group, text="Завантажити", command=self._open_batch_modal).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(files_group, text="Папка", command=self._open_folder).pack(side="left", fill="x", expand=True, padx=(4, 0))

        ads_group = self._action_group(btn_frame, "AdsPower", 1)
        ctk.CTkButton(ads_group, text="Відкрити ADS", command=self._launch_adspower).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(ads_group, text="Відв'язати", fg_color="#6a4c93", hover_color="#4a3570",
                      command=self._unlink_adspower).pack(side="left", fill="x", expand=True, padx=(4, 0))

        mexc_group = self._action_group(btn_frame, "MEXC", 2)
        ctk.CTkButton(mexc_group, text="Open", command=self._run_open_mexc).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(mexc_group, text="Register", fg_color="#1f538d",
                      hover_color="#143a63", command=self._run_register_mexc).pack(side="left", fill="x", expand=True, padx=(4, 0))

        account_group = self._action_group(btn_frame, "Акаунт", 3)
        ctk.CTkButton(account_group, text="Зберегти", fg_color="#b35b04",
                      hover_color="#d9710b", command=self._save_account).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ctk.CTkButton(account_group, text="Видалити", fg_color="#8b0000",
                      hover_color="#5c0000", command=self._delete_account).pack(side="left", fill="x", expand=True, padx=(4, 0))
        lbl_status = ctk.CTkLabel(account_workspace, text="", font=ctk.CTkFont(size=12))
        lbl_status.grid(row=2, column=0, pady=(6, 4))

        workspace = {
            "account": account,
            "tab_name": tab_name,
            "details_tab": details_tab,
            "activity_log": activity_log,
            "lbl_status": lbl_status,
        }
        self._account_workspaces[account.email] = workspace
        self._workspace_by_tab[tab_name] = account.email
        self._render_account_tab_bar()
        return workspace

    def _activate_account_workspace(self, email: str) -> bool:
        workspace = self._account_workspaces.get(email)
        if not workspace:
            return False
        self.current_account = workspace["account"]
        self.details_tab = workspace["details_tab"]
        self.activity_log = workspace["activity_log"]
        self.lbl_status = workspace["lbl_status"]
        self.account_list.set_current(email)
        return True

    def _close_current_account_tab(self) -> None:
        if not self.current_account:
            return
        email = self.current_account.email
        workspace = self._account_workspaces.get(email)
        if not workspace:
            return
        if email in self._running_accounts:
            self._cancel_running_account_operation(email)
        workspace["details_tab"].flush_autosave()
        workspace["details_tab"].dispose()
        tab_name = workspace["tab_name"]
        self._account_workspaces.pop(email, None)
        self._workspace_by_tab.pop(tab_name, None)
        self.event_service.clear_account(email)
        self._delete_account_tab(tab_name)

        if self._account_workspaces:
            next_email = next(iter(self._account_workspaces))
            next_workspace = self._account_workspaces[next_email]
            self._set_account_tab(next_workspace["tab_name"])
            self._activate_account_workspace(next_email)
        else:
            self.current_account = None
            self.details_tab = None
            self.activity_log = None
            self.lbl_status = self.lbl_account_tabs_status
            self.tabview.set("Акаунти")

    def _cancel_running_account_operation(self, account_email: str) -> None:
        for task_id, scenario in list(self._task_scenarios.items()):
            scenario_account = getattr(scenario, "account", None)
            if getattr(scenario_account, "email", "") != account_email:
                continue
            cancel = getattr(scenario, "cancel", None)
            if callable(cancel):
                cancel()
            task = self.task_service.get_task(task_id)
            self.event_service.emit(
                f"Operation cancelled because the account tab was closed: {account_email}",
                account_email=account_email,
                task_id=task_id,
                event_type="task_failed",
                level="error",
                data={"scenario_type": task.scenario_type if task else ""},
            )
            break

    def _create_pending_workspace(self, key: str, title: str, message: str, *, account_email: str = ""):
        tab_name = title
        counter = 2
        while (
            tab_name in self._workspace_by_tab
            or any(ws["tab_name"] == tab_name for ws in self._pending_workspaces.values())
        ):
            tab_name = f"{title} ({counter})"
            counter += 1
        tab = self._add_account_tab_frame(tab_name)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(tab, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        header.grid_columnconfigure(0, weight=1)
        status_label = ctk.CTkLabel(
            header,
            text=message,
            text_color="#7CFFB2",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        status_label.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            header,
            text="Закрити вкладку",
            width=120,
            fg_color="#555555",
            hover_color="#444444",
            command=lambda k=key: self._close_pending_workspace(k),
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))

        log = ActivityLogPanel(tab)
        log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log.clear()
        log.add(message, "info")

        workspace = {
            "tab_name": tab_name,
            "account_email": account_email,
            "status_label": status_label,
            "activity_log": log,
        }
        self._pending_workspaces[key] = workspace
        self._set_account_tab(tab_name)
        self.tabview.set("Акаунт")
        self.lbl_status = status_label
        self.activity_log = log
        return workspace

    def _update_pending_workspace(self, key: str, message: str, level: str = "info") -> None:
        workspace = self._pending_workspaces.get(key)
        if not workspace:
            return
        workspace["status_label"].configure(
            text=message,
            text_color="red" if level == "error" else ("#7CFFB2" if level == "success" else "#ffb74d"),
        )
        workspace["activity_log"].add(message, level)

    def _close_pending_workspace(self, key: str) -> None:
        workspace = self._pending_workspaces.pop(key, None)
        if not workspace:
            return
        tab_name = workspace["tab_name"]
        self._delete_account_tab(tab_name)
        if self.current_account:
            current_workspace = self._account_workspaces.get(self.current_account.email)
            if current_workspace:
                self._set_account_tab(current_workspace["tab_name"])
                self._activate_account_workspace(self.current_account.email)
        else:
            self.lbl_status = self.lbl_account_tabs_status
            self.activity_log = None

    def _remove_pending_workspace(self, key: str) -> None:
        if key in self._pending_workspaces:
            self._close_pending_workspace(key)

    # ── Account loading ──

    def _select_first_account(self):
        email = self.account_service.get_first_email()
        if email:
            self.load_account(email, open_account_tab=False)

    def load_account(self, email, *, open_account_tab=True):
        if self.details_tab:
            self.details_tab.flush_autosave()
        account = self.account_service.get_account(email)
        if not account:
            return
        workspace = self._account_workspaces.get(email)
        if not workspace:
            workspace = self._create_account_workspace(account)
        else:
            workspace["account"] = account
        self._set_account_tab(workspace["tab_name"])
        self._activate_account_workspace(email)
        tags = self.account_service.get_account_tags(email)
        workspace["details_tab"].display(account, tags=tags)
        self.account_list.set_current(email)
        if open_account_tab:
            self.tabview.set("Акаунт")

    # ── Autosave ──

    def _autosave(self, silent=False):
        if not self.current_account or not self.details_tab:
            return
        account = self.details_tab.collect()
        self._preserve_ads_fields(account, self.current_account)

        old_status = self.current_account.status
        status_changed = old_status != account.status

        try:
            self.account_service.save_account(account, old_status=old_status if status_changed else None)
        except Exception as e:
            self._show_status(f"Помилка збереження: {e}", "red")
            return

        self.current_account = account
        workspace = self._account_workspaces.get(account.email)
        if workspace:
            workspace["account"] = account
        self.details_tab.update_profit(account)

        if status_changed:
            self.account_list.update_row_status(account.email, account.status)
            if self.account_list.get_filter() != FILTER_ALL:
                self.account_list.apply_filter()

        if not silent:
            self._show_status("💾 Авто-збережено", "#2fa572")

    # ── Account CRUD ──

    def _create_account(self):
        dialog = ctk.CTkInputDialog(text="Введіть Email нового акаунта:", title="Новий акаунт")
        email = dialog.get_input()
        if not email:
            return

        self._show_status("Створення акаунта...", "#2fa572")
        pending_key = f"create:{email.lower()}"
        self._create_pending_workspace(
            pending_key,
            f"Creating {email}",
            f"Creating account profile for {email}...",
            account_email=email,
        )
        self.event_service.emit(
            f"Account creation started: {email}",
            account_email=email,
            event_type="account_create_started",
            level="info",
        )

        def worker():
            result = self.profile_creation.create_with_manual_email(email)
            self.after(0, lambda: self._on_profile_creation_done(result, pending_key=pending_key))

        threading.Thread(target=worker, daemon=True).start()

    def _create_account_icloud(self):
        self._show_status("Створення iCloud маски + AdsPower профілю...", "#2fa572")
        pending_key = f"create:icloud:{uuid.uuid4().hex[:8]}"
        self._create_pending_workspace(
            pending_key,
            "Creating iCloud",
            "Creating iCloud mask and AdsPower profile...",
        )
        self.event_service.emit(
            "iCloud account creation started",
            event_type="account_create_started",
            level="info",
        )

        def progress(step, fields):
            self.after(0, lambda s=step, f=fields: self._record_icloud_creation_progress(pending_key, s, f))

        def worker():
            result = self.profile_creation.create_with_icloud(progress_callback=progress)
            self.after(0, lambda: self._on_profile_creation_done(result, pending_key=pending_key))

        threading.Thread(target=worker, daemon=True).start()

    def _record_icloud_creation_progress(self, pending_key: str, step: str, fields: dict | None = None) -> None:
        fields = fields or {}
        messages = {
            "start": ("Starting iCloud email creation...", "info"),
            "open_icloud": ("Opening iCloud Hide My Email...", "info"),
            "extra_tabs_closed": (f"Closed extra AdsPower tabs: {fields.get('count', 0)}", "warning"),
            "icloud_loaded": ("iCloud Hide My Email loaded.", "success"),
            "existing_addresses_detected": ("Existing iCloud addresses checked.", "info"),
            "create_address_open": ("Opening new email form...", "info"),
            "generated_address_wait": ("Waiting for generated iCloud address...", "info"),
            "generated_address_ready": (f"Generated iCloud email: {fields.get('email', '')}", "success"),
            "label_fill": ("Saving iCloud label...", "info"),
            "submit_create": ("Creating iCloud email address...", "info"),
            "confirm_create": ("Confirming iCloud email address...", "info"),
            "completed": (f"iCloud email created: {fields.get('email', '')}", "success"),
            "failed": ("iCloud email creation stopped.", "error"),
        }
        message, level = messages.get(step, (step.replace("_", " "), "info"))
        self._update_pending_workspace(pending_key, message, level)
        self.event_service.emit(
            message,
            account_email=str(fields.get("email") or ""),
            event_type="icloud_create_step",
            level=level,
            data={"step": step, **self._safe_event_data(fields)},
        )

    def _on_profile_creation_done(self, result, pending_key: str | None = None):
        if result.success:
            if pending_key:
                self._update_pending_workspace(pending_key, result.message, "success")
                self._remove_pending_workspace(pending_key)
            self._reload_account_list()
            if result.email:
                self.load_account(result.email)
                if pending_key and pending_key.startswith("create:icloud:"):
                    self.event_service.emit(
                        f"iCloud email created: {result.email}",
                        account_email=result.email,
                        event_type="icloud_email_created",
                        level="success",
                    )
                if result.ads_profile_id:
                    self.event_service.emit(
                        f"AdsPower profile linked: {result.email}",
                        account_email=result.email,
                        event_type="adspower_profile_ready",
                        level="success",
                    )
        elif pending_key:
            self._update_pending_workspace(pending_key, result.message, "error")
        self.event_service.emit(
            result.message,
            account_email=result.email,
            event_type="account_create_completed" if result.success else "account_create_failed",
            level="success" if result.success else "error",
        )
        self._show_status(result.message, "green" if result.success else "red")

    def _save_account(self):
        if not self.current_account:
            self._show_status("Спочатку створіть або виберіть акаунт зліва!", "red")
            return
        self.details_tab._cancel_autosave()

        entered_email = self.details_tab.get_entered_email()
        if entered_email and entered_email != self.current_account.email:
            old_email = self.current_account.email
            success = self.account_service.rename_account(old_email, entered_email)
            if success:
                self.current_account.email = entered_email
                self.details_tab._current_email = entered_email
                self.details_tab.lbl_editing_status.configure(text=entered_email)
                workspace = self._account_workspaces.pop(old_email, None)
                if workspace:
                    workspace["account"] = self.current_account
                    self._account_workspaces[entered_email] = workspace
                    self._workspace_by_tab[workspace["tab_name"]] = entered_email
                self._reload_account_list()
            else:
                self._show_status("Помилка перейменування!", "red")
                self.details_tab.set_entered_email(self.current_account.email)
                return

        self._autosave(silent=True)
        self._reload_account_list()
        self.account_list.set_current(self.current_account.email)
        workspace = self._account_workspaces.get(self.current_account.email)
        if workspace:
            workspace["account"] = self.current_account
        self._show_status("Зміни успішно збережено!", "green")

    @staticmethod
    def _preserve_ads_fields(target: Account, source: Account) -> None:
        target.ads_profile_id = source.ads_profile_id
        target.ads_serial_number = source.ads_serial_number
        target.ads_link_status = source.ads_link_status
        target.ads_manual_unlink = source.ads_manual_unlink
        target.ads_last_seen_at = source.ads_last_seen_at
        target.ads_profile_name = source.ads_profile_name
        target.ads_conflict_reason = source.ads_conflict_reason
        target.old_email = source.old_email
        target.text_notes = source.text_notes
        target.invested = source.invested
        target.deposit = source.deposit
        target.balance = source.balance
        target.net_profit = source.net_profit

    def _delete_account(self):
        if not self.current_account:
            return

        def on_confirm():
            self.details_tab._cancel_autosave()
            email = self.current_account.email
            self.account_service.delete_account(email)
            workspace = self._account_workspaces.pop(email, None)
            if workspace:
                tab_name = workspace["tab_name"]
                self._workspace_by_tab.pop(tab_name, None)
                self._delete_account_tab(tab_name)
            self.current_account = None
            self.details_tab = None
            self.activity_log = None
            self.lbl_status = self.lbl_account_tabs_status
            self.account_list.remove_row(email)
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
        workspace = self._account_workspaces.get(email)
        if workspace:
            workspace["account"].status = new_status
            workspace["details_tab"].status_var.set(new_status)

        self.account_list.update_row_status(email, new_status)
        if self.account_list.get_filter() != FILTER_ALL:
            self.account_list.apply_filter()
        self._show_status(f"Тег → {TAG_SHORT.get(new_status, new_status)}, папку переміщено", "#2fa572")

    # ── AdsPower ──

    def _reload_account_list(self):
        accounts_with_tags = self.account_service.get_accounts_with_tags(
            archived_only=self.account_list.get_view_mode() == VIEW_ARCHIVE,
        )
        self.account_list.load_all(accounts_with_tags=accounts_with_tags)

    def _on_account_list_view_change(self, _view_name: str):
        self._reload_account_list()

    def _sync_adspower_on_startup(self):
        self.account_list.set_loading(True, "AdsPower API...")

        def worker():
            if not self.adspower.is_running():
                self.after(0, lambda: self.account_list.set_loading(False))
                return
            try:
                stats = self.account_service.sync_with_adspower(self.adspower)
                self._save_sync_timestamp()

                def on_done():
                    self.account_list.set_loading(False)
                    self._reload_account_list()
                    if self.current_account:
                        self.account_list.set_current(self.current_account.email)
                    if stats.get("created") or stats.get("linked") or stats.get("renamed") or stats.get("name_conflicts"):
                        self._show_status(self._format_sync_message(stats), "green")

                self.after(0, on_done)
            except Exception:
                self.after(0, lambda: self.account_list.set_loading(False))

        threading.Thread(target=worker, daemon=True).start()

    def _manual_sync_adspower(self):
        self._show_status("Синхронізація з AdsPower...", "#2fa572")
        self.account_list.set_loading(True, "Синхронізація...")

        def worker():
            try:
                if not self.adspower.is_running():
                    if not self._request_adspower_url_and_retry():
                        self.after(0, lambda: self._show_status(
                            "AdsPower Local API недоступний. Вкажіть порт або URL у налаштуваннях.",
                            "red",
                        ))
                        return
                stats = self.account_service.sync_with_adspower(self.adspower)
                self._save_sync_timestamp()

                def on_done():
                    self._reload_account_list()
                    if self.current_account:
                        self.account_list.set_current(self.current_account.email)
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
                self.after(0, lambda: self.account_list.set_loading(False))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_adspower_settings(self, api_key: str | None = None, base_url: str | None = None):
        api_key = self.settings.get("adspower_api_key", "") if api_key is None else api_key
        base_url = self.settings.get("adspower_base_url", "") if base_url is None else base_url
        self.adspower.api_key = api_key
        self.adspower.base_url = self._normalize_adspower_base_url(base_url)

    @staticmethod
    def _normalize_adspower_base_url(value: str) -> str:
        value = (value or "").strip().rstrip("/")
        if not value:
            return "http://local.adspower.net:50401"
        if value.isdigit():
            return f"http://127.0.0.1:{value}"
        if "://" not in value:
            return f"http://{value}"
        return value

    def _request_adspower_url_and_retry(self) -> bool:
        result = {"url": ""}
        done = threading.Event()

        def ask():
            current_url = self.settings.get("adspower_base_url", "") or self.adspower.base_url
            dialog = ctk.CTkInputDialog(
                title="AdsPower Local API",
                text=(
                    "Не вдалося підключитися до AdsPower Local API.\n\n"
                    "Введіть порт або повний URL:\n"
                    "Наприклад: 50500 або http://127.0.0.1:50500"
                ),
            )
            entered = dialog.get_input()
            result["url"] = entered or ""
            done.set()

        self.after(0, ask)
        done.wait()

        entered_url = result["url"].strip()
        if not entered_url:
            return False

        base_url = self._normalize_adspower_base_url(entered_url)
        self.settings.set("adspower_base_url", base_url)
        self._apply_adspower_settings(base_url=base_url)
        self.after(0, lambda: self._set_settings_ads_base_url(base_url))
        self.after(0, lambda: self._show_status(f"Пробую AdsPower Local API: {base_url}", "#2fa572"))
        return self.adspower.is_running()

    def _set_settings_ads_base_url(self, base_url: str) -> None:
        if not hasattr(self, "settings_tab"):
            return
        entry = getattr(self.settings_tab, "entry_ads_base_url", None)
        if not entry:
            return
        entry.delete(0, "end")
        entry.insert(0, base_url)

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
                def on_done():
                    if self.current_account and self.current_account.email == email:
                        self.current_account.ads_remark = remark
                    workspace = self._account_workspaces.get(email)
                    if workspace:
                        workspace["account"].ads_remark = remark
                    self._reload_account_list()
                    self.account_list.set_current(email)
                    self._show_status("Remark збережено в акаунті та AdsPower!", "green")

                self.after(0, on_done)
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
                self.event_service.emit(
                    "AdsPower profile is already open.",
                    account_email=account.email,
                    event_type="adspower_open",
                    level="success",
                )
                self.after(0, lambda: self._show_status("Профіль вже відкритий!", "#2fa572"))
                return

            conn = self.adspower.start_browser(profile_id)
            if conn:
                self.event_service.emit(
                    "AdsPower profile opened.",
                    account_email=account.email,
                    event_type="adspower_open",
                    level="success",
                )
                self.after(0, lambda: self._show_status("AdsPower профіль запущено!", "green"))
            else:
                self.event_service.emit(
                    "Failed to open AdsPower profile.",
                    account_email=account.email,
                    event_type="adspower_open_failed",
                    level="error",
                )
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
            workspace = self._account_workspaces.get(email)
            if workspace and self.current_account:
                workspace["account"] = self.current_account
                tags = self.account_service.get_account_tags(email)
                workspace["details_tab"].display(self.current_account, tags=tags)
            self._reload_account_list()
            self.account_list.set_current(email)
            self._show_status("AdsPower profile unlinked locally.", "green")
        else:
            self._show_status("Failed to unlink AdsPower profile.", "red")

    # ── Automation ──

    def _submit_scenario_task(self, scenario_type: str, scenario, on_complete, status_message: str):
        scenario_account = getattr(scenario, "account", None)
        account_email = getattr(scenario_account, "email", "")
        if account_email in self._running_accounts:
            self._show_status("This account already has a running operation.", "#ff9800")
            return None
        task = self.task_service.create_task(account_email, scenario_type)
        self.task_service.start_task(task.id)
        scenario.task_id = task.id
        scenario.progress_reporter = lambda step, fields: self._record_scenario_progress(
            task.id,
            scenario_type,
            step,
            fields,
        )
        debug = getattr(scenario, "debug", None)
        if debug and hasattr(debug, "bind_progress_reporter"):
            debug.bind_progress_reporter(
                lambda step, fields, level: self._record_scenario_progress(
                    task.id,
                    scenario_type,
                    step,
                    fields,
                    level=level,
                )
            )
        self._running_accounts.add(account_email)
        self._task_scenarios[task.id] = scenario
        wrapped_on_complete = lambda done_task_id, result: self._finish_scenario_task(
            done_task_id,
            result,
            account_email,
            on_complete,
        )
        self.scenario_runner.submit(task.id, scenario, on_complete=wrapped_on_complete)
        self._show_status(status_message, "#2fa572")
        return task

    def _record_scenario_progress(
        self,
        task_id: str,
        scenario_type: str,
        step: str,
        fields,
        *,
        level: str = "info",
    ) -> None:
        presentation = format_progress_step(
            scenario_type,
            step,
            level=level,
            data=self._safe_event_data(fields),
        )
        if not presentation:
            return
        self.task_service.record_step(
            task_id,
            presentation.step,
            message=presentation.message,
            level=presentation.level,
            data={
                "source_step": step,
                "checkpoint": presentation.checkpoint,
            },
        )

    def _finish_scenario_task(self, task_id: str, result, account_email: str, on_complete) -> None:
        try:
            on_complete(task_id, result)
        finally:
            self._running_accounts.discard(account_email)
            self._task_scenarios.pop(task_id, None)

    @staticmethod
    def _safe_event_data(fields):
        if not isinstance(fields, dict):
            return {}
        safe = {}
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, (list, tuple)):
                safe[key] = [
                    item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                    for item in value[:20]
                ]
            elif isinstance(value, dict):
                safe[key] = {
                    str(k): v if isinstance(v, (str, int, float, bool)) or v is None else str(v)
                    for k, v in list(value.items())[:30]
                }
            else:
                safe[key] = str(value)
        return safe

    def _read_latest_mexc_deposit(self):
        if not self.current_account:
            self._show_status("Select an account first.", "red")
            return

        self.details_tab.flush_autosave()
        account = self.current_account
        if not account.api_key or not account.secret_key:
            self._show_status("Save MEXC API Key and Secret Key first.", "red")
            return

        account_email = account.email
        api_key = account.api_key
        secret_key = account.secret_key
        self._show_status("Reading latest MEXC deposit...", "#2fa572")

        def worker():
            try:
                deposit = MexcApiClient(api_key, secret_key).latest_successful_deposit(days=90)
            except Exception as exc:
                error = str(exc)
                self.after(0, lambda: self._on_latest_mexc_deposit_failed(account_email, error))
                return
            self.after(0, lambda: self._on_latest_mexc_deposit_loaded(account_email, deposit))

        threading.Thread(target=worker, daemon=True).start()

    def _run_find_deposit_screenshot(self):
        if not self.current_account:
            self._show_status("Select an account first.", "red")
            return

        self.details_tab.flush_autosave()
        account = self.current_account
        account_dir = self.account_service.get_account_dir(account.email)
        if not account_dir:
            self._show_status("Account folder was not found.", "red")
            return

        deposit_path = account_dir / "rk_deposit.json"
        if not deposit_path.exists():
            self._show_status("Run Last Deposit first: rk_deposit.json is missing.", "red")
            return

        main_profile_id = (self.settings.get("icloud_ads_profile_id", "") or "").strip()
        if not main_profile_id:
            self._show_status("Set iCloud Profile ID in Settings first.", "red")
            return

        scenario = MexcDepositScreenshotScenario(
            adspower=self.adspower,
            account=account,
            captcha_service=self.captcha_service,
            main_profile_id=main_profile_id,
            account_dir=account_dir,
        )
        self._submit_scenario_task(
            "find_deposit_screenshot",
            scenario,
            self._on_find_deposit_screenshot_complete,
            "Finding RK deposit screenshot...",
        )

    def _on_find_deposit_screenshot_complete(self, task_id: str, result):
        self.task_service.complete_task(task_id, result)

        def update_ui():
            if result.success:
                path = result.data.get("screenshot_path", "")
                account_email = result.data.get("account_email", "")
                if account_email:
                    self.event_service.emit(
                        f"RK deposit screenshot saved: {path}",
                        account_email=account_email,
                        task_id=task_id,
                        event_type="rk_deposit_screenshot_saved",
                        level="success",
                        data={"path": path},
                    )
                self._show_status(result.message, "green")
            else:
                self._show_status(clean_error_message(result.message), "red")
                self._prompt_retry_failed_task(task_id, result.message)

        self.after(0, update_ui)

    def _on_latest_mexc_deposit_loaded(self, account_email: str, deposit) -> None:
        if deposit is None:
            self.event_service.emit(
                "No successful MEXC deposit found in the last 90 days.",
                account_email=account_email,
                event_type="mexc_latest_deposit_read",
                level="warning",
            )
            self._show_status("No successful MEXC deposit found in the last 90 days.", "#ff9800")
            return

        try:
            deposit_path = self._save_rk_deposit_data(account_email, deposit)
        except Exception as exc:
            self._on_latest_mexc_deposit_failed(account_email, f"Failed to save rk_deposit.json: {exc}")
            return

        time_text = self._format_mexc_timestamp(deposit.insert_time)
        message = (
            f"Account: {account_email}\n\n"
            f"Saved: {deposit_path}\n\n"
            f"Time: {time_text}\n"
            f"Amount: {deposit.amount} {deposit.coin}\n"
            f"Network: {deposit.network or '-'}\n"
            f"Address: {deposit.address or '-'}\n"
            f"Memo: {deposit.memo or '-'}\n"
            f"TXID: {deposit.tx_id or '-'}"
        )
        self.event_service.emit(
            f"Latest MEXC deposit saved: {deposit.amount} {deposit.coin} at {time_text}",
            account_email=account_email,
            event_type="mexc_latest_deposit_read",
            level="success",
            data={**deposit.to_dict(), "path": str(deposit_path)},
        )
        self._show_status(f"Latest deposit saved: {deposit.amount} {deposit.coin}", "green")
        messagebox.showinfo("Latest MEXC Deposit", message, parent=self)

    def _save_rk_deposit_data(self, account_email: str, deposit) -> str:
        account_dir = self.account_service.get_account_dir(account_email)
        if not account_dir:
            raise RuntimeError("account folder was not found")
        account_dir.mkdir(parents=True, exist_ok=True)
        path = account_dir / "rk_deposit.json"
        payload = {
            **deposit.to_dict(),
            "source": "mexc_deposit_history_api",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _on_latest_mexc_deposit_failed(self, account_email: str, error: str) -> None:
        message = clean_error_message(error)
        self.event_service.emit(
            f"Failed to read latest MEXC deposit: {message}",
            account_email=account_email,
            event_type="mexc_latest_deposit_read",
            level="error",
        )
        self._show_status(message, "red")

    @staticmethod
    def _format_mexc_timestamp(timestamp_ms: int) -> str:
        if not timestamp_ms:
            return "-"
        return datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

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

    def _on_scenario_complete(self, task_id: str, result):
        self.task_service.complete_task(task_id, result)
        color = "green" if result.success else "red"
        message = result.message if result.success else clean_error_message(result.message)
        self.after(0, lambda: self._show_status(message, color))
        if not result.success:
            self.after(0, lambda: self._prompt_retry_failed_task(task_id, result.message))

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

    def _ask_network_recovery_action(self, account_email: str, step_name: str, state: PageState) -> str:
        result = {"action": "wait"}
        done = threading.Event()

        def ask():
            dialog = ctk.CTkToplevel(self)
            dialog.title("Network loading")
            dialog.geometry("500x240")
            dialog.transient(self)
            dialog.grab_set()
            dialog.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                dialog,
                text=f"Page is not ready for {account_email}",
                font=ctk.CTkFont(size=16, weight="bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
            ctk.CTkLabel(
                dialog,
                text=(
                    f"Step: {step_name}\n"
                    f"Detected state: {state.name}\n\n"
                    "The page may still be loading or the connection/proxy is unstable."
                ),
                justify="left",
                anchor="w",
                wraplength=460,
            ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

            buttons = ctk.CTkFrame(dialog, fg_color="transparent")
            buttons.grid(row=2, column=0, sticky="e", padx=18, pady=(0, 18))

            def choose(action: str):
                result["action"] = action
                try:
                    dialog.destroy()
                finally:
                    done.set()

            ctk.CTkButton(buttons, text="Чекати ще", width=110, command=lambda: choose("wait")).pack(side="left", padx=(0, 8))
            ctk.CTkButton(buttons, text="Оновити сторінку", width=130, command=lambda: choose("refresh")).pack(side="left", padx=(0, 8))
            ctk.CTkButton(buttons, text="Скасувати", width=100, fg_color="#555555",
                          hover_color="#444444", command=lambda: choose("cancel")).pack(side="left")
            dialog.protocol("WM_DELETE_WINDOW", lambda: choose("wait"))

        self.after(0, ask)
        done.wait()
        return result["action"]

    def _manual_assist_for_scenario(
        self,
        scenario,
        step_name: str,
        allowed_states: set[str],
        initial_state: PageState,
    ) -> ManualAssistResult:
        result = {"action": ManualAssistAction.TIMEOUT, "state": initial_state}
        action_event = threading.Event()
        dialog_state = {}
        deadline = time.time() + 600
        account_email = getattr(getattr(scenario, "account", None), "email", "")
        task_id = getattr(scenario, "task_id", "")
        self.event_service.emit(
            f"Manual control is needed for {account_email or 'this account'}",
            account_email=account_email,
            task_id=task_id,
            event_type="manual_assist_required",
            level="warning",
            data={
                "step": step_name,
                "current_screen": initial_state.name,
            },
        )

        def create_dialog():
            dialog = ctk.CTkToplevel(self)
            dialog.title("Manual assist")
            dialog.geometry("560x330")
            dialog.transient(self)
            dialog.grid_columnconfigure(0, weight=1)

            title = ctk.CTkLabel(
                dialog,
                text="Manual control is needed",
                font=ctk.CTkFont(size=16, weight="bold"),
                anchor="w",
            )
            title.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
            status = ctk.CTkLabel(
                dialog,
                text=(
                    f"Step: {step_name}\n"
                    f"Current screen: {initial_state.name}\n\n"
                    "Use the AdsPower browser manually. I will keep watching for a known screen."
                ),
                justify="left",
                anchor="w",
                wraplength=520,
            )
            status.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 14))

            buttons = ctk.CTkFrame(dialog, fg_color="transparent")
            buttons.grid(row=2, column=0, sticky="e", padx=18, pady=(8, 18))

            def choose(action: str):
                result["action"] = action
                try:
                    dialog.destroy()
                except Exception:
                    pass
                action_event.set()

            continue_button = ctk.CTkButton(
                buttons,
                text="Продовжити",
                width=110,
                state="disabled",
                command=lambda: choose(ManualAssistAction.CONTINUE),
            )
            continue_button.pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                buttons,
                text="Почати заново",
                width=120,
                fg_color="#6a4c93",
                hover_color="#4a3570",
                command=lambda: choose(ManualAssistAction.RESTART),
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                buttons,
                text="Скасувати",
                width=100,
                fg_color="#555555",
                hover_color="#444444",
                command=lambda: choose(ManualAssistAction.CANCEL),
            ).pack(side="left")

            def hide_only():
                try:
                    dialog.withdraw()
                except Exception:
                    pass

            dialog.protocol("WM_DELETE_WINDOW", hide_only)
            dialog_state.update({
                "dialog": dialog,
                "status": status,
                "continue": continue_button,
            })

        self.after(0, create_dialog)

        while time.time() < deadline and not action_event.is_set():
            cancel_event = getattr(scenario, "cancel_event", None)
            if cancel_event and cancel_event.is_set():
                result["action"] = ManualAssistAction.CANCEL
                action_event.set()
                break
            state = scenario.state_analyzer.analyze(getattr(scenario, "driver", None))
            result["state"] = state

            def update_state(s=state):
                status = dialog_state.get("status")
                dialog = dialog_state.get("dialog")
                continue_button = dialog_state.get("continue")
                if not status:
                    return
                recognized = s.name in allowed_states and s.confidence >= 0.72
                status.configure(
                    text=(
                        f"Step: {step_name}\n"
                        f"Current screen: {s.name} ({s.confidence:.0%})\n\n"
                        + (
                            "Known screen detected. Click Continue when ready."
                            if recognized
                            else "Use the browser manually. Watching for a known screen..."
                        )
                    )
                )
                if recognized and continue_button:
                    continue_button.configure(state="normal")
                    if dialog:
                        try:
                            dialog.deiconify()
                            dialog.lift()
                        except Exception:
                            pass

            self.after(0, update_state)
            if state.name in allowed_states and state.confidence >= 0.72:
                while time.time() < deadline and not action_event.is_set():
                    time.sleep(0.2)
                break
            time.sleep(3)

        if not action_event.is_set():
            result["action"] = ManualAssistAction.TIMEOUT
            self.after(0, lambda: dialog_state.get("dialog") and dialog_state["dialog"].destroy())
        return ManualAssistResult(result["action"], result["state"])

    def _save_link_mexc_2fa_secret_early(self, account_email: str, two_fa_secret: str) -> None:
        done = threading.Event()

        def save():
            try:
                account = self.account_service.get_account(account_email)
                if account:
                    account.two_fa_secret = two_fa_secret
                    self.account_service.save_account(account)
                    workspace = self._account_workspaces.get(account_email)
                    if workspace:
                        workspace["account"] = account
                        workspace["details_tab"].two_fa_widget.set_secret(two_fa_secret)
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
                        workspace = self._account_workspaces.get(account_email)
                        if workspace:
                            workspace["account"] = account
                            workspace["details_tab"].entry_pass.delete(0, 'end')
                            workspace["details_tab"].entry_pass.insert(0, password)
                        if self.current_account and self.current_account.email == account_email:
                            self.current_account = account
                            self.details_tab.entry_pass.delete(0, 'end')
                            self.details_tab.entry_pass.insert(0, password)
                if account_email:
                    self.event_service.emit(
                        f"MEXC registration completed: {account_email}",
                        account_email=account_email,
                        task_id=task_id,
                        event_type="mexc_registration_completed",
                        level="success",
                    )
                self._show_status(result.message, "green")
            else:
                self._show_status(clean_error_message(result.message), "red")
                self._prompt_retry_failed_task(task_id, result.message)

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
                        workspace = self._account_workspaces.get(account_email)
                        if workspace:
                            workspace["account"] = account
                            workspace["details_tab"].two_fa_widget.set_secret(two_fa_secret)
                        if self.current_account and self.current_account.email == account_email:
                            self.current_account = account
                            self.details_tab.two_fa_widget.set_secret(two_fa_secret)
                self._show_status(result.message, "green")
                if after_success:
                    self.after(100, after_success)
            else:
                self._show_status(clean_error_message(result.message), "red")
                self._prompt_retry_failed_task(task_id, result.message)

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
                        workspace = self._account_workspaces.get(account_email)
                        if workspace:
                            workspace["account"] = account
                            workspace["details_tab"].entry_api.delete(0, 'end')
                            workspace["details_tab"].entry_api.insert(0, api_key)
                            workspace["details_tab"].entry_secret.delete(0, 'end')
                            workspace["details_tab"].entry_secret.insert(0, secret_key)
                        if self.current_account and self.current_account.email == account_email:
                            self.current_account = account
                            self.details_tab.entry_api.delete(0, 'end')
                            self.details_tab.entry_api.insert(0, api_key)
                            self.details_tab.entry_secret.delete(0, 'end')
                            self.details_tab.entry_secret.insert(0, secret_key)
                self._show_status(result.message, "green")
            else:
                self._show_status(clean_error_message(result.message), "red")
                self._prompt_retry_failed_task(task_id, result.message)

        self.after(0, update_ui)

    def _prompt_retry_failed_task(self, task_id: str, error: str) -> None:
        task = self.task_service.get_task(task_id)
        if not task or task.status == "waiting_user":
            return
        issue = self.error_classifier.classify(error)
        page_state = self._analyze_failed_task_state(task_id)
        self.task_service.pause_for_user(
            task_id,
            issue.user_message,
            current_step=task.current_step,
            resume_data={
                "scenario_type": task.scenario_type,
                "account_email": task.account_email,
                "issue_type": issue.issue_type,
                "page_state": page_state.name,
            },
        )
        step_text = task.current_step or "unknown"
        action = self._ask_retry_action(
            account_email=task.account_email,
            issue_message=issue.user_message,
            last_step=step_text,
            page_state=page_state.name,
        )
        if action == "cancel":
            return
        self.task_service.mark_retrying(task_id)
        self.load_account(task.account_email)
        self.after(
            100,
            lambda: self._retry_task_scenario(
                task.scenario_type,
                continue_existing=(action == "continue"),
                issue_type=issue.issue_type,
            ),
        )

    def _analyze_failed_task_state(self, task_id: str):
        scenario = self._task_scenarios.get(task_id)
        driver = getattr(scenario, "driver", None)
        return self.mexc_state_analyzer.analyze(driver)

    def _ask_retry_action(
        self,
        *,
        account_email: str,
        issue_message: str,
        last_step: str,
        page_state: str,
    ) -> str:
        result = {"action": "cancel"}
        dialog = ctk.CTkToplevel(self)
        dialog.title("Operation stopped")
        dialog.geometry("520x300")
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dialog,
            text=f"Operation stopped for {account_email}",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        body = (
            f"What happened: {issue_message}\n\n"
            f"Last checkpoint: {last_step}\n"
            f"Current screen: {page_state}\n\n"
            "Choose how to continue."
        )
        ctk.CTkLabel(dialog, text=body, justify="left", anchor="w", wraplength=480).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=18,
            pady=(0, 14),
        )
        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="e", padx=18, pady=(8, 18))

        def choose(action: str):
            result["action"] = action
            dialog.destroy()

        ctk.CTkButton(buttons, text="Продовжити", width=110, command=lambda: choose("continue")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(buttons, text="Почати заново", width=120, fg_color="#6a4c93",
                      hover_color="#4a3570", command=lambda: choose("restart")).pack(side="left", padx=(0, 8))
        ctk.CTkButton(buttons, text="Скасувати", width=100, fg_color="#555555",
                      hover_color="#444444", command=lambda: choose("cancel")).pack(side="left")

        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
        self.wait_window(dialog)
        return result["action"]

    def _retry_task_scenario(
        self,
        scenario_type: str,
        *,
        continue_existing: bool = True,
        issue_type: str = IssueType.UNKNOWN,
    ) -> None:
        if continue_existing and issue_type == IssueType.BROWSER_CLOSED:
            self._launch_adspower()
            self.after(1200, lambda: self._retry_task_scenario(
                scenario_type,
                continue_existing=False,
                issue_type=issue_type,
            ))
            return
        if scenario_type == "open_mexc":
            self._run_open_mexc()
        elif scenario_type == "register_mexc":
            self._run_register_mexc()
        elif scenario_type == "link_mexc_2fa":
            self._run_link_mexc_2fa()
        elif scenario_type == "create_mexc_api":
            self._run_create_mexc_api(skip_existing_prompt=True)
        else:
            self._show_status(f"Unknown scenario type: {scenario_type}", "red")

    def _on_captcha_notification(self, notification):
        msg = f"CAPTCHA: {notification.account_email} — перейдіть в браузер!"
        self.event_service.emit(
            msg,
            account_email=notification.account_email,
            task_id=notification.task_id,
            event_type="captcha_required",
            level="warning",
        )
        self.after(0, lambda: self._show_status(msg, "#ff9800"))

    def _should_alert_operation_event(self, event) -> bool:
        important_types = {
            "account_create_completed",
            "account_create_failed",
            "captcha_required",
            "manual_assist_required",
            "mexc_registration_completed",
            "task_completed",
            "task_failed",
            "task_waiting_user",
        }
        if event.event_type not in important_types:
            return False

        outcome_types = {"mexc_registration_completed", "task_completed", "task_failed"}
        if event.event_type in outcome_types and event.task_id:
            key = f"outcome:{event.task_id}:{event.level}"
        else:
            key = f"{event.event_type}:{event.task_id}:{event.account_email}:{event.level}"
        now = time.time()
        last_at = self._recent_notification_alerts.get(key, 0)
        if now - last_at < 6:
            return False
        self._recent_notification_alerts[key] = now
        if len(self._recent_notification_alerts) > 80:
            cutoff = now - 120
            self._recent_notification_alerts = {
                item_key: item_time
                for item_key, item_time in self._recent_notification_alerts.items()
                if item_time >= cutoff
            }
        return True

    @staticmethod
    def _operation_event_data(event) -> dict:
        if not getattr(event, "data", ""):
            return {}
        try:
            value = json.loads(event.data)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _operation_alert_text(self, event) -> tuple[str, str]:
        data = self._operation_event_data(event)
        email = event.account_email or data.get("account_email") or ""
        scenario = data.get("scenario_type") or ""
        scenario_titles = {
            "register_mexc": "MEXC registration",
            "link_mexc_2fa": "MEXC 2FA",
            "create_mexc_api": "MEXC API",
            "open_mexc": "MEXC profile",
        }
        scenario_title = scenario_titles.get(scenario, "Operation")

        if event.event_type == "mexc_registration_completed":
            return "Registration completed", f"MEXC account is ready: {email or event.message}"
        if event.event_type == "task_completed":
            return "Operation completed", f"{scenario_title} completed" + (f": {email}" if email else "")
        if event.event_type in ("task_failed", "account_create_failed"):
            return "Operation failed", clean_error_message(event.message)
        if event.event_type in ("manual_assist_required", "task_waiting_user"):
            return "Manual action needed", event.message
        if event.event_type == "captcha_required":
            return "CAPTCHA needed", event.message
        if event.event_type == "account_create_completed":
            return "Account created", event.message
        return "Notification", event.message

    @staticmethod
    def _notification_colors(level: str) -> tuple[str, str]:
        if level == "success":
            return "#123524", "#7CFFB2"
        if level == "error":
            return "#3a1717", "#ff7777"
        if level == "warning":
            return "#3b2b10", "#ffca6a"
        return "#1b2d3d", "#dce4ee"

    @staticmethod
    def _play_operation_sound(level: str) -> None:
        try:
            import winsound

            sound = {
                "success": winsound.MB_ICONASTERISK,
                "warning": winsound.MB_ICONEXCLAMATION,
                "error": winsound.MB_ICONHAND,
            }.get(level, winsound.MB_OK)
            winsound.MessageBeep(sound)
        except Exception:
            pass

    def _show_operation_toast(self, event) -> None:
        title, message = self._operation_alert_text(event)
        bg_color, accent_color = self._notification_colors(event.level)

        if self._notification_toast_after_id:
            try:
                self.after_cancel(self._notification_toast_after_id)
            except Exception:
                pass
            self._notification_toast_after_id = None
        if self._notification_toast:
            try:
                self._notification_toast.destroy()
            except Exception:
                pass

        toast = ctk.CTkFrame(self, fg_color=bg_color, corner_radius=8, border_width=1, border_color=accent_color)
        toast.place(relx=1.0, y=26, x=-24, anchor="ne")
        toast.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            toast,
            text=title,
            text_color=accent_color,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=(14, 10), pady=(10, 2))
        ctk.CTkLabel(
            toast,
            text=message,
            text_color="#f2f5f7",
            anchor="w",
            justify="left",
            wraplength=360,
        ).grid(row=1, column=0, sticky="ew", padx=(14, 10), pady=(0, 10))
        ctk.CTkButton(
            toast,
            text="x",
            width=26,
            height=24,
            fg_color="transparent",
            hover_color="#2b3036",
            command=lambda: self._dismiss_operation_toast(toast),
        ).grid(row=0, column=1, rowspan=2, sticky="ne", padx=(0, 8), pady=8)
        toast.lift()
        self._notification_toast = toast
        self._play_operation_sound(event.level)
        self._notification_toast_after_id = self.after(6500, lambda: self._dismiss_operation_toast(toast))

    def _dismiss_operation_toast(self, toast=None) -> None:
        target = toast or self._notification_toast
        if not target:
            return
        if self._notification_toast_after_id:
            try:
                self.after_cancel(self._notification_toast_after_id)
            except Exception:
                pass
            self._notification_toast_after_id = None
        try:
            target.destroy()
        except Exception:
            pass
        if target is self._notification_toast:
            self._notification_toast = None

    def _on_operation_event(self, event):
        def update_ui():
            workspace = self._account_workspaces.get(event.account_email)
            if workspace:
                workspace["activity_log"].add(event.message, event.level)
            if event.level in ("warning", "error", "success"):
                color = {
                    "warning": "#ff9800",
                    "error": "red",
                    "success": "green",
                }.get(event.level, "white")
                active_event = (
                    self.current_account
                    and event.account_email
                    and event.account_email == self.current_account.email
                )
                if active_event and self.lbl_status:
                    target_label = self.lbl_status
                    target_label.configure(text=event.message, text_color=color)
                    self.after(3000, lambda: target_label and target_label.configure(text=""))
                elif not workspace:
                    self._show_status(event.message, color)
                if self._should_alert_operation_event(event):
                    self._show_operation_toast(event)

        self.after(0, update_ui)

    # ── Tab management ──

    def _on_tab_change(self):
        if self.tabview.get() == "Акаунт" and not self.current_account:
            self.tabview.set("Акаунти")

    def _on_account_tab_change(self):
        tab_name = self._get_account_tab()
        email = self._workspace_by_tab.get(tab_name, "")
        if email:
            self._activate_account_workspace(email)
            return
        pending_key = self._pending_key_for_tab(tab_name)
        pending = self._pending_workspaces.get(pending_key) if pending_key else None
        if pending:
            self.current_account = None
            self.details_tab = None
            self.activity_log = pending["activity_log"]
            self.lbl_status = pending["status_label"]

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
        if self.lbl_status:
            self.lbl_status.configure(text=text, text_color=color)
        if getattr(self, "activity_log", None):
            level = "info"
            color_text = str(color).lower()
            if color_text in ("red", "#ff4444", "#8b0000") or "помилка" in str(text).lower() or "failed" in str(text).lower():
                level = "error"
            elif color_text in ("green", "#2fa572", "#00ff00") or "успіш" in str(text).lower():
                level = "success"
            elif color_text in ("#ff9800", "orange", "#ffb74d"):
                level = "warning"
            self.activity_log.add(text, level)
        target_label = self.lbl_status
        self.after(3000, lambda: target_label and target_label.configure(text=""))

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
                if self.tabview.get() == "Акаунт":
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
        for workspace in list(self._account_workspaces.values()):
            workspace["details_tab"].flush_autosave()
            workspace["details_tab"].dispose()
        self.event_service.clear_all()
        self.scenario_runner.shutdown()
        self.destroy()
