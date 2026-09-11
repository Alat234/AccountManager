import customtkinter as ctk
import os
import time
from datetime import datetime
from tkinter import filedialog
from PIL import ImageGrab, Image
import tkinter as tk


def open_delete_modal(parent, account_name, confirm_callback):
    confirm_modal = ctk.CTkToplevel(parent)
    confirm_modal.title("Підтвердження")
    confirm_modal.geometry("350x150")
    confirm_modal.transient(parent)
    confirm_modal.grab_set()
    confirm_modal.geometry(f"+{parent.winfo_x() + 350}+{parent.winfo_y() + 300}")

    ctk.CTkLabel(confirm_modal, text=f"Видалити акаунт {account_name} назавжди?\n(Папка з файлами також буде видалена)",
                 font=ctk.CTkFont(weight="bold")).pack(pady=20)

    def on_confirm():
        confirm_callback()
        confirm_modal.destroy()

    btn_frame = ctk.CTkFrame(confirm_modal, fg_color="transparent")
    btn_frame.pack(fill="x", padx=20)
    ctk.CTkButton(btn_frame, text="Ні, скасувати", command=confirm_modal.destroy, fg_color="gray").pack(side="left",
                                                                                                        padx=10)
    ctk.CTkButton(btn_frame, text="Так, видалити", command=on_confirm, fg_color="red", hover_color="darkred").pack(
        side="right", padx=10)


def open_captcha_modal(parent, account_email: str, on_dismiss=None):
    modal = ctk.CTkToplevel(parent)
    modal.title("CAPTCHA")
    modal.geometry("420x190")
    modal.transient(parent)
    modal.attributes("-topmost", True)
    modal.geometry(f"+{parent.winfo_x() + 400}+{parent.winfo_y() + 250}")

    ctk.CTkLabel(
        modal,
        text=(
            "CAPTCHA detected.\n\n"
            f"Account: {account_email}\n\n"
            "Solve it in the AdsPower browser window.\n"
            "Registration will continue automatically."
        ),
        font=ctk.CTkFont(weight="bold", size=14),
        text_color="#ff9800",
        justify="center",
    ).pack(pady=20, padx=20)

    def dismiss():
        if on_dismiss:
            on_dismiss()
        modal.destroy()

    ctk.CTkButton(modal, text="OK", command=dismiss).pack(pady=(0, 15))
    return modal


class RKDepositsModal(ctk.CTkToplevel):
    def __init__(self, parent, account_email: str, deposits: list[dict], on_save=None, on_find=None):
        super().__init__(parent)
        self.title("RK Deposits")
        self.geometry("860x520")
        self.transient(parent)
        self.grab_set()
        self.geometry(f"+{parent.winfo_x() + 300}+{parent.winfo_y() + 120}")

        self.account_email = account_email
        self.deposits = deposits
        self.on_save = on_save
        self.on_find = on_find
        self.rows: list[tuple[ctk.BooleanVar, dict]] = []

        self._build()

    def _build(self):
        ctk.CTkLabel(
            self,
            text=f"RK deposits for {self.account_email}",
            font=ctk.CTkFont(weight="bold", size=16),
        ).pack(anchor="w", padx=18, pady=(16, 6))

        ctk.CTkLabel(
            self,
            text="Select deposits for screenshot search. Newest is selected by default.",
            text_color="#aeb6c2",
        ).pack(anchor="w", padx=18, pady=(0, 10))

        header = ctk.CTkFrame(self, fg_color="#23272f")
        header.pack(fill="x", padx=18, pady=(0, 4))
        for index, (text, width) in enumerate([
            ("Use", 56),
            ("Time", 150),
            ("Amount", 130),
            ("Network", 100),
            ("Address", 190),
            ("TXID", 190),
        ]):
            ctk.CTkLabel(header, text=text, width=width, anchor="w", font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=index, padx=6, pady=8, sticky="w"
            )

        scroll = ctk.CTkScrollableFrame(self, height=310)
        scroll.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        for index, deposit in enumerate(self.deposits):
            self._render_deposit_row(scroll, deposit, checked=index == 0)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(0, 16))
        self.warning_label = ctk.CTkLabel(actions, text="", text_color="#ff6b6b")
        self.warning_label.pack(side="left")
        ctk.CTkButton(actions, text="Cancel", width=100, fg_color="#59606b", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        ctk.CTkButton(actions, text="Find Screenshots", width=145, fg_color="#7a5c1e", hover_color="#5d4617",
                      command=self._find).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="Save Selection", width=130, fg_color="#2f6f52", hover_color="#255842",
                      command=self._save).pack(side="right")

    def _render_deposit_row(self, parent, deposit: dict, checked: bool):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        selected = ctk.BooleanVar(value=checked)
        self.rows.append((selected, deposit))

        fields = [
            self._format_time(deposit.get("insert_time")),
            f"{deposit.get('amount') or '-'} {deposit.get('coin') or ''}".strip(),
            deposit.get("network") or "-",
            self._short(deposit.get("address")),
            self._short(deposit.get("tx_id")),
        ]
        ctk.CTkCheckBox(row, text="", variable=selected, width=56).grid(row=0, column=0, padx=6, pady=7, sticky="w")
        for index, (text, width) in enumerate(zip(fields, [150, 130, 100, 190, 190]), start=1):
            ctk.CTkLabel(row, text=text, width=width, anchor="w").grid(row=0, column=index, padx=6, pady=7, sticky="w")

    def _save(self):
        selected = self._selected_deposits()
        if not any(item.get("selected") for item in selected):
            self._warn("Select at least one deposit.")
            return
        if self.on_save:
            self.on_save(selected)
        self.destroy()

    def _find(self):
        selected = self._selected_deposits()
        if not any(item.get("selected") for item in selected):
            self._warn("Select at least one deposit.")
            return
        if self.on_find:
            self.on_find(selected)
        self.destroy()

    def _selected_deposits(self) -> list[dict]:
        selected_ids = {id(deposit) for selected, deposit in self.rows if selected.get()}
        return [{**deposit, "selected": id(deposit) in selected_ids} for deposit in self.deposits]

    def _warn(self, text: str):
        self.warning_label.configure(text=text)
        self.after(3000, lambda: self.warning_label.configure(text=""))

    @staticmethod
    def _format_time(timestamp_ms):
        try:
            value = int(timestamp_ms or 0)
        except (TypeError, ValueError):
            value = 0
        if not value:
            return "-"
        return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _short(value, *, keep: int = 8) -> str:
        text = str(value or "")
        if not text:
            return "-"
        if len(text) <= keep * 2 + 3:
            return text
        return f"{text[:keep]}...{text[-keep:]}"


class BatchUploadModal(ctk.CTkToplevel):
    def __init__(self, parent, account_name, acc_dir, success_callback):
        super().__init__(parent)
        self.title(f"Накопичувач файлів для: {account_name}")
        self.geometry("650x600")
        self.transient(parent)
        self.grab_set()

        # Центрування
        self.geometry(f"+{parent.winfo_x() + 200}+{parent.winfo_y() + 50}")

        self.acc_dir = acc_dir
        self.success_callback = success_callback
        self.entry_widgets = []

        self.bind("<Control-KeyPress>", self.modal_universal_shortcuts)
        self.setup_ui()
        self.add_from_clipboard()

    def setup_ui(self):
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(top_bar, text="📋 Вставити скріншот", command=self.add_from_clipboard, fg_color="#b35b04",
                      hover_color="#d9710b").pack(side="left", padx=5)
        ctk.CTkButton(top_bar, text="➕ Вибрати файли з ПК", command=self.add_from_file_dialog, fg_color="#1f538d").pack(
            side="right", padx=5)

        self.lbl_warn = ctk.CTkLabel(self, text="", text_color="red")
        self.lbl_warn.pack()

        self.scroll = ctk.CTkScrollableFrame(self, width=600, height=400)
        self.scroll.pack(pady=5, padx=10, fill="both", expand=True)

        ctk.CTkButton(self, text="💾 Зберегти всі файли у папку акаунта", fg_color="green", hover_color="darkgreen",
                      command=self.save_batch_action).pack(pady=15)

    def modal_universal_shortcuts(self, event):
        focused = self.focus_get()
        is_text_widget = isinstance(focused, (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text))
        keysym_lower = getattr(event, 'keysym', '').lower()

        if event.keycode == 86:
            if is_text_widget:
                if keysym_lower != 'v':
                    focused.event_generate("<<Paste>>")
                    return "break"
            else:
                self.add_from_clipboard()
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

    def show_warning(self, text):
        self.lbl_warn.configure(text=text)
        self.after(3000, lambda: self.lbl_warn.configure(text=""))

    def render_image_row(self, img, default_name):
        frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        frame.pack(pady=5, fill="x")

        preview_img = img.copy()
        preview_img.thumbnail((150, 100))
        ctk_img = ctk.CTkImage(light_image=preview_img, dark_image=preview_img, size=preview_img.size)

        ctk.CTkLabel(frame, image=ctk_img, text="").pack(side="left", padx=10)

        name_entry = ctk.CTkEntry(frame, width=250)
        name_entry.insert(0, default_name)
        name_entry.pack(side="left", padx=10, fill="x", expand=True)

        item_data = (img, name_entry)
        self.entry_widgets.append(item_data)

        def remove_row():
            frame.destroy()
            if item_data in self.entry_widgets:
                self.entry_widgets.remove(item_data)

        btn_delete = ctk.CTkButton(frame, text="❌", width=30, fg_color="#8b0000", hover_color="#5c0000",
                                   command=remove_row)
        btn_delete.pack(side="right", padx=10)

    def add_from_clipboard(self):
        try:
            img_data = ImageGrab.grabclipboard()
        except Exception:
            self.show_warning("Помилка читання буфера обміну.");
            return

        if img_data is None:
            self.show_warning("У буфері зараз немає картинки!");
            return

        if isinstance(img_data, list):
            for path in img_data:
                if path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                    try:
                        self.render_image_row(Image.open(path), os.path.basename(path))
                    except:
                        pass
        else:
            self.render_image_row(img_data, f"screen_{int(time.time())}.png")

    def add_from_file_dialog(self):
        file_paths = filedialog.askopenfilenames(
            title="Виберіть зображення",
            filetypes=[("Зображення", "*.png *.jpg *.jpeg *.webp")]
        )
        for path in file_paths:
            try:
                self.render_image_row(Image.open(path), os.path.basename(path))
            except:
                pass


    def save_batch_action(self):
        if not self.entry_widgets:
            self.show_warning("Спочатку додайте файли!");
            return

        count = 0
        try:
            for img, entry in self.entry_widgets:
                name = entry.get().strip()
                if not name.endswith(('.png', '.jpg', '.jpeg')): name += ".png"
                img.save(self.acc_dir / name)
                count += 1

            # Викликаємо колбек, який ми передали з головного вікна
            if self.success_callback:
                self.success_callback(count)

            self.destroy()
        except Exception as e:
            self.show_warning(f"Помилка збереження: {str(e)}")
