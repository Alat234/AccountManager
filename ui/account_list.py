import customtkinter as ctk

from models.account import ADS_CONFLICT, ADS_LINKED, ADS_ORPHANED
from storage.constants import (
    STATUSES, TAG_SHORT, SHORT_TO_STATUS, TAG_VALUES, TAG_COLORS, FILTER_ALL,
    ADS_TAG_COLORS, ADS_TAG_DEFAULT_COLOR,
)
from services.account_service import AccountService


class AccountListPanel:

    def __init__(self, parent, account_service: AccountService,
                 on_select=None, on_status_change=None):
        self.parent = parent
        self.account_service = account_service
        self.on_select = on_select
        self.on_status_change = on_status_change

        self.account_buttons = {}
        self.account_rows = {}
        self._ordered_emails = []
        self._empty_label = None
        self._problem_label = None
        self._search_after_id = None
        self._current_email = None

        self._build(parent)

    def _build(self, frame):
        frame.grid_rowconfigure(6, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.logo_label = ctk.CTkLabel(frame, text="Мої Акаунти",
                                       font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(15, 6))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=4)
        btn_frame.grid_columnconfigure((0, 1), weight=1)

        self.btn_new_acc = ctk.CTkButton(btn_frame, text="+ Створити", fg_color="green",
                                         hover_color="darkgreen", height=28)
        self.btn_new_acc.grid(row=0, column=0, sticky="ew", padx=(0, 3))

        self.btn_icloud = ctk.CTkButton(btn_frame, text="iCloud + ADS",
                                        fg_color="#1f538d", hover_color="#143a63", height=28)
        self.btn_icloud.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        self.search_var = ctk.StringVar()
        self.entry_search = ctk.CTkEntry(frame, placeholder_text="Пошук за поштою...",
                                         textvariable=self.search_var, height=28)
        self.entry_search.grid(row=2, column=0, sticky="ew", padx=10, pady=3)
        self.entry_search.bind("<KeyRelease>", self._on_search_changed)

        self.filter_var = ctk.StringVar(value=FILTER_ALL)
        self.opt_filter = ctk.CTkOptionMenu(frame, values=[FILTER_ALL] + TAG_VALUES,
                                            variable=self.filter_var, height=26,
                                            command=lambda c: self.apply_filter())
        self.opt_filter.grid(row=3, column=0, sticky="ew", padx=10, pady=3)

        self.view_var = ctk.StringVar(value="Всі")
        self.view_toggle = ctk.CTkSegmentedButton(
            frame, values=["Всі", "ADS"],
            variable=self.view_var,
            command=self._on_view_change,
        )
        self.view_toggle.grid(row=4, column=0, sticky="ew", padx=10, pady=3)

        self.sync_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.btn_sync = ctk.CTkButton(
            self.sync_frame, text="Синхронізувати",
            fg_color="#1f538d", hover_color="#143a63", width=140, height=26,
        )
        self.btn_sync.pack(side="left", padx=(0, 6))
        self.lbl_last_sync = ctk.CTkLabel(
            self.sync_frame, text="", text_color="gray",
            font=ctk.CTkFont(size=10),
        )
        self.lbl_last_sync.pack(side="left")

        self.accounts_list_frame = ctk.CTkScrollableFrame(frame, label_text="Список:")
        self.accounts_list_frame.grid(row=6, column=0, sticky="nsew", padx=6, pady=(4, 6))

    def set_create_command(self, command):
        self.btn_new_acc.configure(command=command)

    def set_icloud_command(self, command):
        self.btn_icloud.configure(command=command)

    def set_sync_command(self, command):
        self.btn_sync.configure(command=command)

    def update_last_sync(self, timestamp_str: str):
        self.lbl_last_sync.configure(text=f"Останній: {timestamp_str}")

    def set_current(self, email):
        self._current_email = email
        for acc_email, btn in self.account_buttons.items():
            btn.configure(fg_color="#1f538d" if acc_email == email else "transparent")

    def load_all(self, accounts_with_tags=None):
        for widget in self.accounts_list_frame.winfo_children():
            widget.destroy()
        self.account_buttons = {}
        self.account_rows = {}
        self._ordered_emails = []
        self._empty_label = None
        self._problem_label = None

        if accounts_with_tags is not None:
            for acc, tags in accounts_with_tags:
                email = str(acc.email)
                self._ordered_emails.append(email)
                is_ads = acc.ads_link_status == ADS_LINKED
                self._create_row_widgets(
                    email,
                    acc.status,
                    tags=tags,
                    ads_link_status=acc.ads_link_status,
                    ads_conflict_reason=acc.ads_conflict_reason,
                )
                self.account_rows[email]["is_ads"] = is_ads
                self.account_rows[email]["is_ads_problem"] = acc.ads_link_status in (ADS_CONFLICT, ADS_ORPHANED)
        else:
            for email, status in self.account_service.get_accounts_summary():
                email = str(email)
                self._ordered_emails.append(email)
                self._create_row_widgets(email, status)

        self._ordered_emails.sort(key=lambda s: s.lower())
        self.apply_filter()

    def _create_row_widgets(self, email, status, tags=None, ads_link_status="", ads_conflict_reason=""):
        row = ctk.CTkFrame(self.accounts_list_frame, fg_color="transparent", height=30)
        row.pack_propagate(False)

        btn_color = "#1f538d" if self._current_email == email else "transparent"
        btn = ctk.CTkButton(row, text=email, fg_color=btn_color, border_width=1,
                            text_color=("gray10", "#DCE4EE"), anchor="w",
                            height=26, font=ctk.CTkFont(size=12),
                            command=lambda e=email: self._on_account_click(e))
        btn.pack(side="left", fill="x", expand=True, padx=(0, 3))

        if tags:
            for tag in tags[:2]:
                color = ADS_TAG_COLORS.get(tag.get("color", ""), ADS_TAG_DEFAULT_COLOR)
                text_color = "#000000" if tag.get("color") == "yellow" else "white"
                badge = ctk.CTkLabel(
                    row, text=tag["name"],
                    fg_color=color, corner_radius=4,
                    font=ctk.CTkFont(size=9),
                    text_color=text_color,
                    height=20, padx=4,
                )
                badge.pack(side="left", padx=1)
            if len(tags) > 2:
                ctk.CTkLabel(row, text=f"+{len(tags) - 2}", text_color="gray",
                             font=ctk.CTkFont(size=9), height=20).pack(side="left", padx=1)

        if ads_link_status in (ADS_CONFLICT, ADS_ORPHANED):
            badge_text = "conflict" if ads_link_status == ADS_CONFLICT else "orphan"
            badge = ctk.CTkLabel(
                row,
                text=badge_text,
                fg_color="#8b5e00" if ads_link_status == ADS_CONFLICT else "#663399",
                corner_radius=4,
                font=ctk.CTkFont(size=9),
                text_color="white",
                height=20,
                padx=4,
            )
            badge.pack(side="left", padx=1)

        color = TAG_COLORS.get(status, "#444444")
        opt = ctk.CTkOptionMenu(row, values=TAG_VALUES, width=80, height=24,
                                fg_color=color, button_color=color, button_hover_color=color,
                                font=ctk.CTkFont(size=11),
                                command=lambda choice, e=email: self._on_tag_change(e, SHORT_TO_STATUS[choice]))
        opt.set(TAG_SHORT.get(status, status))
        opt.pack(side="right")

        self.account_rows[email] = {
            "frame": row, "btn": btn, "opt": opt, "status": status,
            "tags": tags or [], "is_ads": False, "is_ads_problem": False,
            "ads_link_status": ads_link_status, "ads_conflict_reason": ads_conflict_reason,
        }
        self.account_buttons[email] = btn

    def _on_account_click(self, email):
        if self.on_select:
            self.on_select(email)

    def _on_tag_change(self, email, new_status):
        if self.on_status_change:
            self.on_status_change(email, new_status)

    def _on_view_change(self, value):
        if value == "ADS":
            self.sync_frame.grid(row=5, column=0, sticky="ew", padx=10, pady=3)
        else:
            self.sync_frame.grid_forget()
        self.apply_filter()

    def apply_filter(self):
        search = (self.search_var.get() or "").strip().lower()
        tag_filter = self.filter_var.get()
        view_mode = self.view_var.get()

        for email in self._ordered_emails:
            info = self.account_rows.get(email)
            if info:
                info["frame"].pack_forget()
        if self._empty_label is not None:
            self._empty_label.pack_forget()
        if self._problem_label is not None:
            self._problem_label.pack_forget()

        shown = 0
        problem_emails = []
        for email in self._ordered_emails:
            info = self.account_rows.get(email)
            if not info:
                continue
            status = info["status"]
            if view_mode == "ADS" and info.get("is_ads_problem", False):
                problem_emails.append(email)
                continue
            if view_mode == "ADS" and not info.get("is_ads", False):
                continue
            if tag_filter != FILTER_ALL and TAG_SHORT.get(status, status) != tag_filter:
                continue
            if search and search not in email.lower():
                continue
            info["frame"].pack(fill="x", pady=1, padx=2)
            shown += 1

        if view_mode == "ADS":
            problem_shown = 0
            for email in problem_emails:
                info = self.account_rows.get(email)
                if not info:
                    continue
                status = info["status"]
                if tag_filter != FILTER_ALL and TAG_SHORT.get(status, status) != tag_filter:
                    continue
                if search and search not in email.lower():
                    continue
                if problem_shown == 0:
                    if self._problem_label is None:
                        self._problem_label = ctk.CTkLabel(
                            self.accounts_list_frame,
                            text="ADS needs action",
                            text_color="#ffb74d",
                            font=ctk.CTkFont(size=11, weight="bold"),
                        )
                    self._problem_label.pack(anchor="w", padx=8, pady=(8, 2))
                info["frame"].pack(fill="x", pady=1, padx=2)
                problem_shown += 1
            shown += problem_shown

        if shown == 0:
            if self._empty_label is None:
                self._empty_label = ctk.CTkLabel(self.accounts_list_frame, text="— нічого не знайдено —",
                                                 text_color="gray")
            self._empty_label.pack(pady=10)

    def update_row_status(self, email, status):
        info = self.account_rows.get(email)
        if not info:
            return
        info["status"] = status
        color = TAG_COLORS.get(status, "#444444")
        info["opt"].configure(fg_color=color, button_color=color, button_hover_color=color)
        info["opt"].set(TAG_SHORT.get(status, status))

    def add_row(self, email, status):
        email = str(email)
        if email in self.account_rows:
            self.update_row_status(email, status)
        else:
            self._create_row_widgets(email, status)
            self._ordered_emails.append(email)
            self._ordered_emails.sort(key=lambda s: s.lower())
        self.apply_filter()

    def remove_row(self, email):
        info = self.account_rows.pop(email, None)
        if info:
            info["frame"].destroy()
        self.account_buttons.pop(email, None)
        if email in self._ordered_emails:
            self._ordered_emails.remove(email)
        self.apply_filter()

    def _on_search_changed(self, _event=None):
        if self._search_after_id is not None:
            try:
                self.parent.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.parent.after(200, self._apply_search)

    def _apply_search(self):
        self._search_after_id = None
        self.apply_filter()

    def get_filter(self):
        return self.filter_var.get()
