import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

from models.account import ADS_CONFLICT, ADS_LINKED, ADS_ORPHANED
from services.account_service import AccountService
from storage.constants import (
    FILTER_ALL,
    SHORT_TO_STATUS,
    STATUS_BANNED,
    STATUS_LOST,
    TAG_COLORS,
    TAG_SHORT,
    TAG_VALUES,
    normalize_ads_tag_color,
    readable_text_color,
)

VIEW_PROFILES = "Профілі"
VIEW_ARCHIVE = "Архів"
ARCHIVE_STATUSES = {STATUS_BANNED, STATUS_LOST}

ROW_HEIGHT = 38
SECTION_HEIGHT = 30
EMPTY_HEIGHT = 44


class AccountListPanel:
    def __init__(
        self,
        parent,
        account_service: AccountService,
        on_select=None,
        on_status_change=None,
        on_copy_email=None,
        on_view_change=None,
    ):
        self.parent = parent
        self.account_service = account_service
        self.on_select = on_select
        self.on_status_change = on_status_change
        self.on_copy_email = on_copy_email
        self.on_view_change = on_view_change

        self.account_buttons = {}
        self.account_rows = {}
        self._ordered_emails = []
        self._items = []
        self._row_tops = []
        self._total_height = 1
        self._search_after_id = None
        self._current_email = None
        self._selected_email = ""
        self._context_email = ""

        self._build(parent)

    def _build(self, frame):
        frame.grid_rowconfigure(6, weight=1)
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

        self.view_var = ctk.StringVar(value=VIEW_PROFILES)
        self.view_toggle = ctk.CTkSegmentedButton(
            filters_frame,
            values=[VIEW_PROFILES, VIEW_ARCHIVE],
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
        self.loading_bar = ctk.CTkProgressBar(
            self.sync_frame,
            width=84,
            height=8,
            mode="indeterminate",
            progress_color="#1fa5ff",
        )
        self.lbl_loading = ctk.CTkLabel(
            self.sync_frame,
            text="",
            text_color="#9aa4ad",
            font=ctk.CTkFont(size=10),
        )
        self.sync_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=4)

        selected_frame = ctk.CTkFrame(frame, fg_color="#15181d", corner_radius=6)
        selected_frame.grid(row=5, column=0, sticky="ew", padx=8, pady=(6, 0))
        selected_frame.grid_columnconfigure(1, weight=1)

        self.lbl_selected = ctk.CTkLabel(
            selected_frame,
            text="Виберіть акаунт",
            text_color="#f2f5f7",
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.lbl_selected.grid(row=0, column=0, sticky="w", padx=(10, 8), pady=7)

        self.selected_tags_frame = ctk.CTkFrame(selected_frame, fg_color="transparent", height=28)
        self.selected_tags_frame.grid(row=0, column=1, sticky="ew", padx=4, pady=5)

        self.selected_status_var = ctk.StringVar(value=TAG_VALUES[0] if TAG_VALUES else "")
        self.opt_selected_status = ctk.CTkOptionMenu(
            selected_frame,
            values=TAG_VALUES,
            variable=self.selected_status_var,
            width=120,
            height=28,
            command=self._on_selected_status_change,
        )
        self.opt_selected_status.grid(row=0, column=3, sticky="e", padx=(6, 4), pady=5)

        self.btn_copy_selected = ctk.CTkButton(
            selected_frame,
            text="Copy",
            width=58,
            height=28,
            fg_color="#343638",
            hover_color="#1f538d",
            command=lambda: self._copy_email(self._selected_email),
        )
        self.btn_copy_selected.grid(row=0, column=4, sticky="e", padx=(4, 10), pady=5)

        list_frame = ctk.CTkFrame(frame, fg_color="#0f1115", corner_radius=6)
        list_frame.grid(row=6, column=0, sticky="nsew", padx=8, pady=(8, 6))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)

        self.header_canvas = tk.Canvas(
            list_frame,
            height=30,
            bd=0,
            highlightthickness=0,
            background="#1b1d20",
        )
        self.header_canvas.grid(row=0, column=0, sticky="ew")

        self.canvas = tk.Canvas(
            list_frame,
            bd=0,
            highlightthickness=0,
            background="#111316",
        )
        self.canvas.grid(row=1, column=0, sticky="nsew")
        self.vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self._on_scrollbar)
        self.vsb.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self._on_canvas_yscroll)

        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.header_canvas.bind("<Configure>", lambda _event: self._draw_header())
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_mousewheel)
        self.canvas.bind("<Button-5>", self._on_mousewheel)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Button-3>", self._show_context_menu)
        self.canvas.bind("<Control-c>", lambda _event: self._copy_selected())
        self.canvas.bind("<Enter>", lambda _event: self.canvas.focus_set())

        self.context_menu = tk.Menu(self.canvas, tearoff=0)
        self.status_menu = tk.Menu(self.canvas, tearoff=0)

    # ── Public hooks ──

    def set_create_command(self, command):
        self.btn_new_acc.configure(command=command)

    def set_icloud_command(self, command):
        self.btn_icloud.configure(command=command)

    def set_sync_command(self, command):
        self.btn_sync.configure(command=command)

    def set_loading(self, active: bool, message: str = ""):
        if active:
            self.lbl_loading.configure(text=message)
            if not self.loading_bar.winfo_ismapped():
                self.loading_bar.pack(side="left", padx=(8, 6))
            if not self.lbl_loading.winfo_ismapped():
                self.lbl_loading.pack(side="left")
            self.loading_bar.start()
            self.btn_sync.configure(state="disabled")
            return
        self.loading_bar.stop()
        self.loading_bar.pack_forget()
        self.lbl_loading.pack_forget()
        self.btn_sync.configure(state="normal")

    def update_last_sync(self, timestamp_str: str):
        self.lbl_last_sync.configure(text=f"Останній: {timestamp_str}")

    def set_current(self, email):
        self._current_email = email
        if not email or email not in self.account_rows:
            return
        self._selected_email = email
        self._sync_selected_controls(email)
        self._scroll_email_into_view(email)
        self._render_visible_rows()

    def load_all(self, accounts_with_tags=None):
        self.account_buttons = {}
        self.account_rows = {}
        self._ordered_emails = []

        if accounts_with_tags is None:
            accounts_with_tags = self.account_service.get_accounts_with_tags(
                archived_only=self.get_view_mode() == VIEW_ARCHIVE,
            )

        for index, (acc, tags) in enumerate(accounts_with_tags):
            email = str(acc.email)
            tag_names = [str(tag.get("name") or tag.get("id") or "") for tag in (tags or [])]
            is_ads = acc.ads_link_status == ADS_LINKED
            is_problem = acc.ads_link_status in (ADS_CONFLICT, ADS_ORPHANED)
            self._ordered_emails.append(email)
            self.account_rows[email] = {
                "email": email,
                "status": acc.status,
                "tags": tags or [],
                "tag_text": ", ".join(name for name in tag_names if name),
                "serial_number": acc.ads_serial_number,
                "remark": acc.ads_remark or "",
                "is_ads": is_ads,
                "is_ads_problem": is_problem,
                "ads_link_status": acc.ads_link_status,
                "ads_conflict_reason": acc.ads_conflict_reason,
                "index": index,
            }

        self.apply_filter()
        if self._current_email:
            self.set_current(self._current_email)

    def apply_filter(self):
        search = (self.search_var.get() or "").strip().lower()
        tag_filter = self.filter_var.get()
        rows = []
        for email in self._ordered_emails:
            info = self.account_rows.get(email)
            if not info or not self._matches_view(info):
                continue
            if tag_filter != FILTER_ALL and TAG_SHORT.get(info["status"], info["status"]) != tag_filter:
                continue
            if search and search not in self._search_blob(email, info):
                continue
            rows.append(email)

        rows.sort(key=self._sort_key)
        items = []
        last_group = None
        for email in rows:
            group = self._group_for_info(self.account_rows[email])
            if group != last_group:
                items.append({"type": "section", "group": group, "height": SECTION_HEIGHT})
                last_group = group
            items.append({"type": "account", "email": email, "height": ROW_HEIGHT})
        if not rows:
            items.append({"type": "empty", "height": EMPTY_HEIGHT})

        self._items = items
        self._rebuild_positions()
        self.canvas.configure(scrollregion=(0, 0, max(1, self.canvas.winfo_width()), self._total_height))
        if self._selected_email and not self._email_is_visible(self._selected_email):
            self._clear_selected_controls()
        self._draw_header()
        self._render_visible_rows()

    def update_row_status(self, email, status):
        info = self.account_rows.get(email)
        if not info:
            return
        info["status"] = status
        self.apply_filter()
        if email == self._selected_email and self._email_is_visible(email):
            self._sync_selected_controls(email)

    def add_row(self, email, status):
        email = str(email)
        self.account_rows[email] = {
            "email": email,
            "status": status,
            "tags": [],
            "tag_text": "",
            "serial_number": 0,
            "remark": "",
            "is_ads": False,
            "is_ads_problem": False,
            "ads_link_status": "",
            "ads_conflict_reason": "",
            "index": len(self._ordered_emails),
        }
        if email not in self._ordered_emails:
            self._ordered_emails.append(email)
        self.apply_filter()

    def remove_row(self, email):
        self.account_rows.pop(email, None)
        self.account_buttons.pop(email, None)
        if email in self._ordered_emails:
            self._ordered_emails.remove(email)
        if email == self._selected_email:
            self._clear_selected_controls()
        self.apply_filter()

    def get_filter(self):
        return self.filter_var.get()

    def get_view_mode(self):
        return self.view_var.get()

    # ── Canvas rendering ──

    def _draw_header(self):
        self.header_canvas.delete("all")
        width = max(1, self.header_canvas.winfo_width())
        columns = self._columns(width)
        self.header_canvas.create_rectangle(0, 0, width, 30, fill="#1b1d20", outline="")
        for key, label in (
            ("serial", "№"),
            ("email", "Пошта"),
            ("tags", "Теги"),
            ("remark", "Зауваження"),
            ("status", "Статус"),
            ("link", "Профіль"),
        ):
            x, col_w = columns[key]
            anchor = "center" if key in {"serial", "status", "link"} else "w"
            text_x = x + col_w / 2 if anchor == "center" else x + 8
            self.header_canvas.create_text(
                text_x,
                15,
                text=label,
                fill="#9aa4ad",
                font=("Helvetica", 10, "bold"),
                anchor=anchor,
            )

    def _render_visible_rows(self):
        self.canvas.delete("row")
        if not self._items:
            return

        width = max(1, self.canvas.winfo_width())
        top = self.canvas.canvasy(0)
        bottom = top + max(1, self.canvas.winfo_height())
        columns = self._columns(width)

        for index, item in enumerate(self._items):
            y = self._row_tops[index]
            height = item["height"]
            if y + height < top or y > bottom:
                continue
            if item["type"] == "section":
                self._draw_section(item, y, height, width)
            elif item["type"] == "account":
                self._draw_account_row(item["email"], y, height, width, columns)
            else:
                self._draw_empty_row(y, height, width)

    def _draw_section(self, item, y, height, width):
        label = self._section_label(item["group"])
        self.canvas.create_rectangle(0, y, width, y + height, fill="#2b2b2b", outline="", tags="row")
        self.canvas.create_text(
            10,
            y + height / 2,
            text=label,
            fill="#ffb74d",
            font=("Helvetica", 10, "bold"),
            anchor="w",
            tags="row",
        )

    def _draw_empty_row(self, y, height, width):
        self.canvas.create_rectangle(0, y, width, y + height, fill="#111316", outline="", tags="row")
        self.canvas.create_text(
            14,
            y + height / 2,
            text="Нічого не знайдено",
            fill="#9aa4ad",
            font=("Helvetica", 11),
            anchor="w",
            tags="row",
        )

    def _draw_account_row(self, email, y, height, width, columns):
        info = self.account_rows[email]
        is_selected = email == self._selected_email
        row_bg = "#173a5e" if is_selected else ("#17191c" if info["index"] % 2 else "#111316")
        self.canvas.create_rectangle(0, y, width, y + height, fill=row_bg, outline="", tags="row")
        self.canvas.create_line(0, y + height - 1, width, y + height - 1, fill="#20242a", tags="row")

        serial = str(info["serial_number"]) if info["serial_number"] else "-"
        serial_color = "#7CFFB2" if info["serial_number"] else "#9aa4ad"
        sx, sw = columns["serial"]
        self.canvas.create_text(
            sx + sw / 2,
            y + height / 2,
            text=serial,
            fill=serial_color,
            font=("Helvetica", 12, "bold"),
            anchor="center",
            tags="row",
        )

        ex, ew = columns["email"]
        self.canvas.create_text(
            ex + 8,
            y + height / 2,
            text=self._fit_text(email, ew - 12),
            fill="#ffffff",
            font=("Helvetica", 12, "bold"),
            anchor="w",
            tags="row",
        )

        tx, tw = columns["tags"]
        self._draw_tag_badges(info.get("tags", []), tx + 6, y + 8, tw - 12, limit=3)

        rx, rw = columns["remark"]
        remark = self._fit_text(info.get("remark", "") or "-", rw - 12)
        self.canvas.create_text(
            rx + 8,
            y + height / 2,
            text=remark,
            fill="#dce4ee",
            font=("Helvetica", 10),
            anchor="w",
            tags="row",
        )

        sx, sw = columns["status"]
        self._draw_status_badge(info["status"], sx + 8, y + 7, sw - 16, height - 14)

        lx, lw = columns["link"]
        self.canvas.create_text(
            lx + lw / 2,
            y + height / 2,
            text=self._link_text(info),
            fill="#dce4ee",
            font=("Helvetica", 10, "bold"),
            anchor="center",
            tags="row",
        )

    def _draw_tag_badges(self, tags, x, y, max_width, *, limit):
        if not tags:
            self.canvas.create_text(
                x,
                y + 10,
                text="-",
                fill="#9aa4ad",
                font=("Helvetica", 10),
                anchor="w",
                tags="row",
            )
            return

        cursor = x
        remaining = max_width
        for tag in tags[:limit]:
            if remaining < 34:
                break
            text = self._fit_text(tag.get("name") or tag.get("id") or "tag", min(84, remaining - 10))
            badge_w = min(max(36, len(text) * 7 + 14), remaining)
            color = normalize_ads_tag_color(tag.get("color", ""))
            self.canvas.create_rectangle(
                cursor,
                y,
                cursor + badge_w,
                y + 22,
                fill=color,
                outline=color,
                tags="row",
            )
            self.canvas.create_text(
                cursor + badge_w / 2,
                y + 11,
                text=text,
                fill=readable_text_color(color),
                font=("Helvetica", 9, "bold"),
                anchor="center",
                tags="row",
            )
            cursor += badge_w + 4
            remaining = max_width - (cursor - x)

        if len(tags) > limit and remaining >= 26:
            self.canvas.create_text(
                cursor + 4,
                y + 11,
                text=f"+{len(tags) - limit}",
                fill="#9aa4ad",
                font=("Helvetica", 9, "bold"),
                anchor="w",
                tags="row",
            )

    def _draw_status_badge(self, status, x, y, width, height):
        color = TAG_COLORS.get(status, "#444444")
        text = self._fit_text(TAG_SHORT.get(status, status), width - 20)
        self.canvas.create_rectangle(x, y, x + width, y + height, fill=color, outline=color, tags="row")
        self.canvas.create_text(
            x + width / 2,
            y + height / 2,
            text=f"{text} ▾",
            fill="#ffffff",
            font=("Helvetica", 9, "bold"),
            anchor="center",
            tags="row",
        )

    def _columns(self, width):
        width = max(width, 760)
        pad = 8
        gap = 6
        serial_w = 58
        status_w = 118
        link_w = 96
        remaining = width - pad * 2 - serial_w - status_w - link_w - gap * 5
        tags_w = max(150, min(230, int(remaining * 0.25)))
        remark_w = max(150, min(300, int(remaining * 0.30)))
        email_w = max(210, remaining - tags_w - remark_w)

        x = pad
        columns = {}
        for key, col_w in (
            ("serial", serial_w),
            ("email", email_w),
            ("tags", tags_w),
            ("remark", remark_w),
            ("status", status_w),
            ("link", link_w),
        ):
            columns[key] = (x, col_w)
            x += col_w + gap
        return columns

    # ── Events ──

    def _on_canvas_configure(self, _event=None):
        self.canvas.configure(scrollregion=(0, 0, max(1, self.canvas.winfo_width()), self._total_height))
        self._draw_header()
        self._render_visible_rows()

    def _on_canvas_yscroll(self, *args):
        self.vsb.set(*args)
        self._render_visible_rows()

    def _on_scrollbar(self, *args):
        self.canvas.yview(*args)
        self._render_visible_rows()

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -int(event.delta / 120) if event.delta else 0
        if delta:
            self.canvas.yview_scroll(delta, "units")
            self._render_visible_rows()
        return "break"

    def _on_canvas_click(self, event):
        item = self._item_at_canvas_y(self.canvas.canvasy(event.y))
        if not item or item.get("type") != "account":
            return
        email = item["email"]
        self._selected_email = email
        self._sync_selected_controls(email)
        self._render_visible_rows()

        column = self._column_at_x(event.x)
        if column == "status":
            self._show_status_menu(email, event.x_root, event.y_root)
            return
        if self.on_select:
            self.on_select(email)

    def _show_context_menu(self, event):
        item = self._item_at_canvas_y(self.canvas.canvasy(event.y))
        if not item or item.get("type") != "account":
            return
        email = item["email"]
        self._context_email = email
        self._selected_email = email
        self._sync_selected_controls(email)
        self._render_visible_rows()

        self.context_menu.delete(0, "end")
        self.context_menu.add_command(label="Відкрити", command=lambda: self._on_account_click(email))
        self.context_menu.add_command(label="Копіювати email", command=lambda: self._copy_email(email))
        self.context_menu.add_separator()
        for short_status in TAG_VALUES:
            self.context_menu.add_command(
                label=f"Статус: {short_status}",
                command=lambda choice=short_status, row_email=email: self._on_tag_change(
                    row_email,
                    SHORT_TO_STATUS[choice],
                ),
            )
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def _show_status_menu(self, email, root_x, root_y):
        self.status_menu.delete(0, "end")
        for short_status in TAG_VALUES:
            self.status_menu.add_command(
                label=short_status,
                command=lambda choice=short_status, row_email=email: self._on_tag_change(
                    row_email,
                    SHORT_TO_STATUS[choice],
                ),
            )
        self.status_menu.tk_popup(root_x, root_y)

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

    def _on_view_change(self, value):
        if value == VIEW_PROFILES:
            self.sync_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=4)
        else:
            self.sync_frame.grid_forget()
        if self.on_view_change:
            self.on_view_change(value)
        else:
            self.apply_filter()

    def _copy_selected(self):
        if self._selected_email:
            self._copy_email(self._selected_email)
        return "break"

    def _on_account_click(self, email):
        if self.on_select:
            self.on_select(email)

    def _copy_email(self, email):
        if email and self.on_copy_email:
            self.on_copy_email(email)

    def _on_tag_change(self, email, new_status):
        if self.on_status_change:
            self.on_status_change(email, new_status)

    def _on_selected_status_change(self, short_status):
        if not self._selected_email or self._selected_email not in self.account_rows:
            return
        self._on_tag_change(self._selected_email, SHORT_TO_STATUS[short_status])

    # ── Data helpers ──

    def _rebuild_positions(self):
        self._row_tops = []
        cursor = 0
        for item in self._items:
            self._row_tops.append(cursor)
            cursor += item["height"]
        self._total_height = max(1, cursor)

    def _item_at_canvas_y(self, canvas_y):
        for index, top in enumerate(self._row_tops):
            item = self._items[index]
            if top <= canvas_y < top + item["height"]:
                return item
        return None

    def _email_is_visible(self, email):
        return any(item.get("type") == "account" and item.get("email") == email for item in self._items)

    def _scroll_email_into_view(self, email):
        for index, item in enumerate(self._items):
            if item.get("type") == "account" and item.get("email") == email:
                top = self._row_tops[index]
                bottom = top + item["height"]
                view_top = self.canvas.canvasy(0)
                view_bottom = view_top + max(1, self.canvas.winfo_height())
                if top < view_top or bottom > view_bottom:
                    self.canvas.yview_moveto(top / self._total_height)
                return

    def _column_at_x(self, x):
        columns = self._columns(max(1, self.canvas.winfo_width()))
        for key, (left, width) in columns.items():
            if left <= x <= left + width:
                return key
        return ""

    def _matches_view(self, info) -> bool:
        status = info.get("status", "")
        if self.get_view_mode() == VIEW_ARCHIVE:
            return status in ARCHIVE_STATUSES
        return status not in ARCHIVE_STATUSES

    def _sort_key(self, email):
        info = self.account_rows.get(email, {})
        group = self._group_for_info(info)
        serial = info.get("serial_number") or 10**9
        return (group, serial, email.lower())

    def _group_for_info(self, info) -> int:
        if self.get_view_mode() == VIEW_ARCHIVE:
            return 0
        if info.get("is_ads"):
            return 0
        if info.get("is_ads_problem"):
            return 1
        return 2

    def _section_label(self, group: int):
        if self.get_view_mode() == VIEW_ARCHIVE:
            return "Архів: бан ф'ючів та дроп загубився"
        return {
            0: "ADS профілі",
            1: "ADS потребує уваги",
            2: "Без ADS",
        }.get(group, "Профілі")

    @staticmethod
    def _link_text(info):
        if info.get("is_ads"):
            return "ADS"
        if info.get("ads_link_status") == ADS_CONFLICT:
            return "conflict"
        if info.get("ads_link_status") == ADS_ORPHANED:
            return "orphan"
        return "local"

    @staticmethod
    def _search_blob(email, info):
        return " ".join(
            [
                str(email),
                str(info.get("serial_number", "")),
                str(info.get("remark", "")),
                str(info.get("tag_text", "")),
                str(info.get("ads_link_status", "")),
                str(info.get("ads_conflict_reason", "")),
                str(TAG_SHORT.get(info.get("status", ""), info.get("status", ""))),
            ]
        ).lower()

    def _sync_selected_controls(self, email: str):
        info = self.account_rows.get(email)
        if not info:
            return
        self._selected_email = email
        serial = f"№ {info['serial_number']}" if info.get("serial_number") else "local"
        self.lbl_selected.configure(text=f"{serial}  {email}")
        short_status = TAG_SHORT.get(info["status"], info["status"])
        self.selected_status_var.set(short_status)
        self._set_status_menu_color(info["status"])
        self._render_selected_tags(info.get("tags", []))

    def _clear_selected_controls(self):
        self._selected_email = ""
        self.lbl_selected.configure(text="Виберіть акаунт")
        self._render_selected_tags([])

    def _set_status_menu_color(self, status: str):
        self._set_menu_color(self.opt_selected_status, status)

    @staticmethod
    def _set_menu_color(menu, status: str):
        color = TAG_COLORS.get(status, "#444444")
        menu.configure(
            fg_color=color,
            button_color=color,
            button_hover_color=color,
        )

    def _render_selected_tags(self, tags):
        for widget in self.selected_tags_frame.winfo_children():
            widget.destroy()
        self._render_tag_badges(self.selected_tags_frame, tags, limit=4, max_len=18)

    def _render_tag_badges(self, parent, tags, *, limit: int, max_len: int):
        if not tags:
            ctk.CTkLabel(
                parent,
                text="-",
                text_color="#9aa4ad",
                height=20,
            ).pack(side="left", padx=(0, 4))
            return
        for tag in tags[:limit]:
            color = normalize_ads_tag_color(tag.get("color", ""))
            ctk.CTkLabel(
                parent,
                text=self._truncate(tag.get("name") or tag.get("id") or "tag", max_len),
                fg_color=color,
                corner_radius=4,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=readable_text_color(color),
                height=20,
                padx=6,
            ).pack(side="left", padx=(0, 4))
        if len(tags) > limit:
            ctk.CTkLabel(
                parent,
                text=f"+{len(tags) - limit}",
                text_color="#9aa4ad",
                height=20,
            ).pack(side="left")

    @staticmethod
    def _fit_text(text, max_width, avg_char_width=7):
        text = str(text or "").strip()
        max_chars = max(1, int(max_width / avg_char_width))
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        return text[: max_chars - 3] + "..."

    @staticmethod
    def _truncate(text, max_len):
        text = str(text or "").strip()
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "..."
