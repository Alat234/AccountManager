import customtkinter as ctk

from models.account import ADS_CONFLICT, ADS_LINKED, ADS_ORPHANED
from services.account_service import AccountService
from storage.constants import (
    ADS_TAG_COLORS,
    ADS_TAG_DEFAULT_COLOR,
    FILTER_ALL,
    SHORT_TO_STATUS,
    TAG_COLORS,
    TAG_SHORT,
    TAG_VALUES,
)


class AccountListPanel:
    def __init__(self, parent, account_service: AccountService,
                 on_select=None, on_status_change=None, on_copy_email=None):
        self.parent = parent
        self.account_service = account_service
        self.on_select = on_select
        self.on_status_change = on_status_change
        self.on_copy_email = on_copy_email

        self.account_buttons = {}
        self.account_rows = {}
        self._ordered_emails = []
        self._empty_label = None
        self._problem_label = None
        self._search_after_id = None
        self._current_email = None

        self._build(parent)

    def _build(self, frame):
        frame.grid_rowconfigure(7, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        self.logo_label = ctk.CTkLabel(
            frame,
            text="Акаунти",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        self.logo_label.grid(row=0, column=0, padx=14, pady=(8, 4), sticky="w")

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.grid(row=1, column=0, sticky="w", padx=14, pady=(2, 4))

        self.btn_new_acc = ctk.CTkButton(
            btn_frame,
            text="+ Створити",
            fg_color="#218a43",
            hover_color="#16652f",
            height=30,
            width=118,
        )
        self.btn_new_acc.grid(row=0, column=0, padx=(0, 8))

        self.btn_icloud = ctk.CTkButton(
            btn_frame,
            text="iCloud + ADS",
            fg_color="#1f538d",
            hover_color="#143a63",
            height=30,
            width=126,
        )
        self.btn_icloud.grid(row=0, column=1)

        self.search_var = ctk.StringVar()
        self.entry_search = ctk.CTkEntry(
            frame,
            placeholder_text="Пошук: №, пошта, тег, зауваження...",
            textvariable=self.search_var,
            height=30,
        )
        self.entry_search.grid(row=2, column=0, sticky="ew", padx=14, pady=(2, 3))
        self.entry_search.bind("<KeyRelease>", self._on_search_changed)

        filters_frame = ctk.CTkFrame(frame, fg_color="transparent")
        filters_frame.grid(row=3, column=0, sticky="ew", padx=14, pady=3)
        filters_frame.grid_columnconfigure((0, 1), weight=1)

        self.filter_var = ctk.StringVar(value=FILTER_ALL)
        self.opt_filter = ctk.CTkOptionMenu(
            filters_frame,
            values=[FILTER_ALL] + TAG_VALUES,
            variable=self.filter_var,
            height=28,
            command=lambda _choice: self.apply_filter(),
        )
        self.opt_filter.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.view_var = ctk.StringVar(value="ADS")
        self.view_toggle = ctk.CTkSegmentedButton(
            filters_frame,
            values=["Всі", "ADS"],
            variable=self.view_var,
            command=self._on_view_change,
        )
        self.view_toggle.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.sync_frame = ctk.CTkFrame(frame, fg_color="transparent")
        self.btn_sync = ctk.CTkButton(
            self.sync_frame,
            text="Синхронізувати AdsPower",
            fg_color="#1f538d",
            hover_color="#143a63",
            height=28,
        )
        self.btn_sync.pack(side="left", padx=(0, 8))
        self.lbl_last_sync = ctk.CTkLabel(
            self.sync_frame,
            text="",
            text_color="gray",
            font=ctk.CTkFont(size=10),
        )
        self.lbl_last_sync.pack(side="left")
        self.sync_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=4)

        header = ctk.CTkFrame(frame, fg_color="#1b1d20", corner_radius=6)
        header.grid(row=5, column=0, sticky="ew", padx=8, pady=(8, 0))
        header.grid_columnconfigure(0, minsize=58, weight=0)
        header.grid_columnconfigure(1, minsize=430, weight=0)
        header.grid_columnconfigure(2, minsize=220, weight=0)
        header.grid_columnconfigure(3, minsize=290, weight=0)
        header.grid_columnconfigure(4, minsize=104, weight=0)
        header.grid_columnconfigure(5, weight=1)
        self._header_label(header, "№", 0, width=44)
        self._header_label(header, "Пошта", 1)
        self._header_label(header, "Тег", 2)
        self._header_label(header, "Зауваження", 3)
        self._header_label(header, "Статус", 4, width=92)

        self.accounts_list_frame = ctk.CTkScrollableFrame(frame, label_text="")
        self.accounts_list_frame.grid(row=7, column=0, sticky="nsew", padx=6, pady=(4, 6))

    @staticmethod
    def _header_label(parent, text, column, width=None):
        kwargs = {}
        if width is not None:
            kwargs["width"] = width
        label = ctk.CTkLabel(
            parent,
            text=text,
            text_color="#9aa4ad",
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
            **kwargs,
        )
        label.grid(row=0, column=column, sticky="ew", padx=6, pady=5)

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
        for acc_email, info in self.account_rows.items():
            selected = acc_email == email
            info["frame"].configure(
                fg_color="#173a5e" if selected else ("#17191c" if info["index"] % 2 else "#111316")
            )
            info["email_btn"].configure(fg_color="transparent")

    def load_all(self, accounts_with_tags=None):
        for widget in self.accounts_list_frame.winfo_children():
            widget.destroy()
        self.account_buttons = {}
        self.account_rows = {}
        self._ordered_emails = []
        self._empty_label = None
        self._problem_label = None

        if accounts_with_tags is not None:
            for index, (acc, tags) in enumerate(accounts_with_tags):
                email = str(acc.email)
                self._ordered_emails.append(email)
                is_ads = acc.ads_link_status == ADS_LINKED
                self._create_row_widgets(
                    email,
                    acc.status,
                    index=index,
                    serial_number=acc.ads_serial_number,
                    remark=acc.ads_remark,
                    tags=tags,
                    ads_link_status=acc.ads_link_status,
                    ads_conflict_reason=acc.ads_conflict_reason,
                )
                self.account_rows[email]["is_ads"] = is_ads
                self.account_rows[email]["is_ads_problem"] = acc.ads_link_status in (ADS_CONFLICT, ADS_ORPHANED)
        else:
            for index, (email, status) in enumerate(self.account_service.get_accounts_summary()):
                email = str(email)
                self._ordered_emails.append(email)
                self._create_row_widgets(email, status, index=index)

        self._ordered_emails.sort(key=lambda s: s.lower())
        self.apply_filter()
        if self._current_email:
            self.set_current(self._current_email)

    def _create_row_widgets(
        self,
        email,
        status,
        *,
        index=0,
        serial_number=0,
        remark="",
        tags=None,
        ads_link_status="",
        ads_conflict_reason="",
    ):
        row_color = "#17191c" if index % 2 else "#111316"
        row = ctk.CTkFrame(self.accounts_list_frame, fg_color=row_color, corner_radius=6, height=44)
        row.pack_propagate(False)
        row.grid_columnconfigure(0, minsize=58, weight=0)
        row.grid_columnconfigure(1, minsize=430, weight=0)
        row.grid_columnconfigure(2, minsize=220, weight=0)
        row.grid_columnconfigure(3, minsize=290, weight=0)
        row.grid_columnconfigure(4, minsize=104, weight=0)
        row.grid_columnconfigure(5, weight=1)

        serial_text = str(serial_number) if serial_number else "-"
        ctk.CTkLabel(
            row,
            text=serial_text,
            width=44,
            text_color="#7CFFB2" if serial_number else "gray",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        email_cell = ctk.CTkFrame(row, fg_color="transparent")
        email_cell.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=6)
        email_cell.grid_columnconfigure(0, weight=1)

        email_btn = ctk.CTkButton(
            email_cell,
            text=email,
            fg_color="transparent",
            hover_color="#24384d",
            text_color=("#111111", "#DCE4EE"),
            anchor="w",
            height=32,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=lambda e=email: self._on_account_click(e),
        )
        email_btn.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            email_cell,
            text="Copy",
            width=54,
            height=28,
            fg_color="#343638",
            hover_color="#1f538d",
            command=lambda e=email: self._copy_email(e),
        ).grid(row=0, column=1, sticky="e", padx=(5, 0))

        tag_frame = ctk.CTkFrame(row, fg_color="transparent")
        tag_frame.grid(row=0, column=2, sticky="ew", padx=2, pady=7)
        self._render_tags(tag_frame, tags or [], ads_link_status)

        remark_text = self._truncate(remark, 26)
        ctk.CTkLabel(
            row,
            text=remark_text if remark_text else "-",
            text_color="#d4d9de" if remark_text else "gray",
            font=ctk.CTkFont(size=12),
            anchor="w",
        ).grid(row=0, column=3, sticky="ew", padx=6, pady=6)

        color = TAG_COLORS.get(status, "#444444")
        opt = ctk.CTkOptionMenu(
            row,
            values=TAG_VALUES,
            width=92,
            height=26,
            fg_color=color,
            button_color=color,
            button_hover_color=color,
            font=ctk.CTkFont(size=11),
            command=lambda choice, e=email: self._on_tag_change(e, SHORT_TO_STATUS[choice]),
        )
        opt.set(TAG_SHORT.get(status, status))
        opt.grid(row=0, column=4, sticky="e", padx=(4, 6), pady=5)

        self.account_rows[email] = {
            "frame": row,
            "email_btn": email_btn,
            "opt": opt,
            "status": status,
            "tags": tags or [],
            "serial_number": serial_number,
            "remark": remark or "",
            "is_ads": False,
            "is_ads_problem": False,
            "ads_link_status": ads_link_status,
            "ads_conflict_reason": ads_conflict_reason,
            "index": index,
        }
        self.account_buttons[email] = email_btn

    def _render_tags(self, parent, tags, ads_link_status):
        shown = tags[:2]
        if shown:
            for tag in shown:
                color = ADS_TAG_COLORS.get(tag.get("color", ""), ADS_TAG_DEFAULT_COLOR)
                text_color = "#000000" if tag.get("color") == "yellow" else "white"
                ctk.CTkLabel(
                    parent,
                    text=self._truncate(tag.get("name") or tag.get("id") or "tag", 16),
                    fg_color=color,
                    corner_radius=4,
                    font=ctk.CTkFont(size=10),
                    text_color=text_color,
                    height=20,
                    padx=5,
                ).pack(side="left", padx=(0, 3))
            if len(tags) > len(shown):
                ctk.CTkLabel(
                    parent,
                    text=f"+{len(tags) - len(shown)}",
                    text_color="gray",
                    font=ctk.CTkFont(size=10),
                    height=20,
                ).pack(side="left")
        elif ads_link_status in (ADS_CONFLICT, ADS_ORPHANED):
            badge_text = "conflict" if ads_link_status == ADS_CONFLICT else "orphan"
            ctk.CTkLabel(
                parent,
                text=badge_text,
                fg_color="#8b5e00" if ads_link_status == ADS_CONFLICT else "#663399",
                corner_radius=4,
                font=ctk.CTkFont(size=10),
                text_color="white",
                height=20,
                padx=5,
            ).pack(side="left")
        else:
            ctk.CTkLabel(parent, text="-", text_color="gray", font=ctk.CTkFont(size=11)).pack(side="left")

    @staticmethod
    def _truncate(text, max_len):
        text = str(text or "").strip()
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "..."

    def _on_account_click(self, email):
        if self.on_select:
            self.on_select(email)

    def _copy_email(self, email):
        if self.on_copy_email:
            self.on_copy_email(email)

    def _on_tag_change(self, email, new_status):
        if self.on_status_change:
            self.on_status_change(email, new_status)

    def _on_view_change(self, value):
        if value == "ADS":
            self.sync_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=4)
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
            if search and search not in self._search_blob(email, info):
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
                if search and search not in self._search_blob(email, info):
                    continue
                if problem_shown == 0:
                    if self._problem_label is None:
                        self._problem_label = ctk.CTkLabel(
                            self.accounts_list_frame,
                            text="ADS потребує уваги",
                            text_color="#ffb74d",
                            font=ctk.CTkFont(size=11, weight="bold"),
                        )
                    self._problem_label.pack(anchor="w", padx=8, pady=(8, 2))
                info["frame"].pack(fill="x", pady=1, padx=2)
                problem_shown += 1
            shown += problem_shown

        if shown == 0:
            if self._empty_label is None:
                self._empty_label = ctk.CTkLabel(
                    self.accounts_list_frame,
                    text="- нічого не знайдено -",
                    text_color="gray",
                )
            self._empty_label.pack(pady=10)

    @staticmethod
    def _search_blob(email, info):
        tag_names = " ".join(tag.get("name", "") for tag in info.get("tags", []))
        return " ".join(
            [
                str(email),
                str(info.get("serial_number", "")),
                str(info.get("remark", "")),
                tag_names,
                str(info.get("ads_link_status", "")),
                str(info.get("ads_conflict_reason", "")),
            ]
        ).lower()

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
            self._create_row_widgets(email, status, index=len(self._ordered_emails))
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
