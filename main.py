import customtkinter as ctk
import os
import time
from tkinter import ttk, filedialog
from PIL import ImageGrab, Image
from core import FileManager, DatabaseManager, STATUSES, BASE_DIR
import tkinter as tk

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Accounts Manager CRM")
        self.geometry("1100x750")

        self.fm = FileManager()
        self.db = DatabaseManager()
        self.current_account = None

        self.setup_ui()
        self.load_accounts_list()
        self.refresh_table()

    def create_entry_with_copy(self, parent, width=150, font=None):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        entry = ctk.CTkEntry(frame, width=width, font=font)
        entry.pack(side="left")

        btn_copy = ctk.CTkButton(frame, text="📋", width=28, fg_color="#343638", hover_color="#1f538d",
                                 command=lambda e=entry: self.copy_to_clipboard(e.get()))
        btn_copy.pack(side="left", padx=(5, 0))

        return frame, entry

    def copy_to_clipboard(self, text):
        if not text:
            self.show_status("Поле порожнє!", "red")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()
        self.show_status("✅ Скопійовано!", "green")

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ================= ЛІВА ПАНЕЛЬ =================
        self.left_frame = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.left_frame.grid(row=0, column=0, sticky="nsew")
        self.left_frame.grid_rowconfigure(2, weight=1)

        self.logo_label = ctk.CTkLabel(self.left_frame, text="Мої Акаунти", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_new_acc = ctk.CTkButton(self.left_frame, text="+ Створити акаунт", fg_color="green",
                                         hover_color="darkgreen", command=self.open_create_dialog)
        self.btn_new_acc.grid(row=1, column=0, padx=20, pady=10)

        self.accounts_list_frame = ctk.CTkScrollableFrame(self.left_frame, label_text="Список:")
        self.accounts_list_frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)

        # ================= ПРАВА ПАНЕЛЬ =================
        self.right_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="transparent")
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.right_frame.grid_columnconfigure(0, weight=1)
        self.right_frame.grid_rowconfigure(0, weight=1)

        # ================= ВКЛАДКИ (TABS) =================
        self.tabview = ctk.CTkTabview(self.right_frame, command=self.on_tab_change)
        self.tabview.grid(row=0, column=0, sticky="nsew")

        tab_main = self.tabview.add("Деталі")
        tab_notes = self.tabview.add("Нотатки")
        tab_table = self.tabview.add("Таблиця (База)")

        # --- ВКЛАДКА 1: ДЕТАЛІ ---
        self.lbl_editing_status = ctk.CTkLabel(tab_main, text="⚙️ Редагування: (не вибрано)",
                                               font=ctk.CTkFont(size=22, weight="bold"), text_color="#1fa5ff")
        self.lbl_editing_status.pack(pady=(15, 0))

        info_frame = ctk.CTkFrame(tab_main, fg_color="transparent")
        info_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkLabel(info_frame, text="Головна пошта:", text_color="gray").grid(row=0, column=0, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Стара пошта:", text_color="gray").grid(row=0, column=1, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Пароль:", text_color="gray").grid(row=0, column=2, sticky="w", padx=5)

        frame_main_email, self.entry_main_email = self.create_entry_with_copy(info_frame, width=180,
                                                                              font=ctk.CTkFont(weight="bold"))
        frame_main_email.grid(row=1, column=0, padx=5, pady=(0, 15), sticky="w")

        frame_old_email, self.entry_old_email = self.create_entry_with_copy(info_frame, width=150)
        frame_old_email.grid(row=1, column=1, padx=5, pady=(0, 15), sticky="w")

        frame_pass, self.entry_pass = self.create_entry_with_copy(info_frame, width=150)
        frame_pass.grid(row=1, column=2, padx=5, pady=(0, 15), sticky="w")

        ctk.CTkLabel(info_frame, text="API Key:", text_color="gray").grid(row=2, column=0, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Secret Key:", text_color="gray").grid(row=2, column=1, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Статус:", text_color="gray").grid(row=2, column=2, sticky="w", padx=5)

        frame_api, self.entry_api = self.create_entry_with_copy(info_frame, width=180)
        frame_api.grid(row=3, column=0, padx=5, pady=(0, 15), sticky="w")

        frame_secret, self.entry_secret = self.create_entry_with_copy(info_frame, width=150)
        frame_secret.grid(row=3, column=1, padx=5, pady=(0, 15), sticky="w")

        self.status_var = ctk.StringVar(value=STATUSES[0])
        self.opt_status = ctk.CTkOptionMenu(info_frame, values=STATUSES, variable=self.status_var, width=150)
        self.opt_status.grid(row=3, column=2, padx=5, pady=(0, 15), sticky="w")

        # Фінанси
        fin_frame = ctk.CTkFrame(tab_main)
        fin_frame.pack(fill="x", pady=10, padx=10)

        ctk.CTkLabel(fin_frame, text="Вкладено ($):", text_color="gray").grid(row=0, column=0, sticky="w", padx=10,
                                                                              pady=(5, 0))
        ctk.CTkLabel(fin_frame, text="Депозит ($):", text_color="gray").grid(row=0, column=1, sticky="w", padx=10,
                                                                             pady=(5, 0))
        ctk.CTkLabel(fin_frame, text="Баланс ($):", text_color="gray").grid(row=0, column=2, sticky="w", padx=10,
                                                                            pady=(5, 0))

        self.entry_invested = ctk.CTkEntry(fin_frame, width=100)
        self.entry_invested.grid(row=1, column=0, padx=10, pady=(0, 10))

        self.entry_deposit = ctk.CTkEntry(fin_frame, width=100)
        self.entry_deposit.grid(row=1, column=1, padx=10, pady=(0, 10))

        self.entry_balance = ctk.CTkEntry(fin_frame, width=100)
        self.entry_balance.grid(row=1, column=2, padx=10, pady=(0, 10))

        self.lbl_profit = ctk.CTkLabel(fin_frame, text="Прибуток: $0.0", font=ctk.CTkFont(size=18, weight="bold"))
        self.lbl_profit.grid(row=0, column=3, rowspan=2, padx=30, pady=10)

        # --- ВКЛАДКА 2: НОТАТКИ ---
        tab_notes.grid_columnconfigure(0, weight=1)
        tab_notes.grid_rowconfigure(0, weight=1)
        self.text_notes = ctk.CTkTextbox(tab_notes)
        self.text_notes.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # --- ВКЛАДКА 3: ТАБЛИЦЯ ---
        self.setup_treeview(tab_table)

        # ================= НИЖНЯ ПАНЕЛЬ КНОПОК =================
        self.btn_frame = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.btn_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.btn_paste_img = ctk.CTkButton(self.btn_frame, text="📋 Завантажити файли", command=self.open_batch_modal)
        self.btn_paste_img.pack(side="left", padx=5)

        self.btn_open_folder = ctk.CTkButton(self.btn_frame, text="📁 Відкрити папку", command=self.open_folder)
        self.btn_open_folder.pack(side="left", padx=5)

        self.btn_delete = ctk.CTkButton(self.btn_frame, text="🗑 Видалити акаунт", fg_color="#8b0000",
                                        hover_color="#5c0000", command=self.delete_current_account)
        self.btn_delete.pack(side="right", padx=5)

        self.btn_save = ctk.CTkButton(self.btn_frame, text="💾 Зберегти зміни", fg_color="#b35b04",
                                      hover_color="#d9710b", command=self.save_current_account)
        self.btn_save.pack(side="right", padx=5)

        self.lbl_status = ctk.CTkLabel(self.right_frame, text="", font=ctk.CTkFont(size=12))
        self.lbl_status.grid(row=2, column=0)

        # --- РОЗУМНЕ ПЕРЕХОПЛЕННЯ КЛАВІШ (Вирішує проблему укр розкладки) ---
        self.bind("<Control-KeyPress>", self.handle_universal_shortcuts)

        self.active_modal = None

    def on_tab_change(self):
        if self.tabview.get() == "Таблиця (База)":
            self.btn_frame.grid_remove()
            self.refresh_table()
        else:
            self.btn_frame.grid()

    def setup_treeview(self, parent_frame):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=30, fieldbackground="#2b2b2b",
                        borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#343638", foreground="white", relief="flat",
                        font=('Helvetica', 10, 'bold'))

        columns = ("email", "old_email", "pass", "api", "profit")
        self.tree = ttk.Treeview(parent_frame, columns=columns, show="headings")

        self.tree.heading("email", text="Пошта")
        self.tree.heading("old_email", text="Стара пошта")
        self.tree.heading("pass", text="Пароль")
        self.tree.heading("api", text="API Key")
        self.tree.heading("profit", text="Прибуток")

        self.tree.column("email", width=150)
        self.tree.column("old_email", width=120)
        self.tree.column("pass", width=100)
        self.tree.column("api", width=120)
        self.tree.column("profit", width=80, anchor="center")

        vsb = ttk.Scrollbar(parent_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(parent_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self.on_tree_double_click)

    # ================= ЛОГІКА ПРОГРАМИ =================

    def show_status(self, text, color="white"):
        self.lbl_status.configure(text=text, text_color=color)
        self.after(3000, lambda: self.lbl_status.configure(text=""))

    def handle_universal_shortcuts(self, event):
        """Ідеально перехоплює Ctrl+C/V/X/A/Z за їхнім апаратним кодом"""
        focused = self.focus_get()
        is_text_widget = isinstance(focused, (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text))

        # Ctrl + V (Вставка) - код 86 на Windows
        if event.keycode == 86 or getattr(event, 'char', '').lower() in ['v', 'м']:
            if is_text_widget:
                focused.event_generate("<<Paste>>")
                return "break"
            else:
                if self.tabview.get() != "Таблиця (База)":
                    self.open_batch_modal()
                return "break"

        # Ctrl + C (Копіювання) - код 67
        elif event.keycode == 67 or getattr(event, 'char', '').lower() in ['c', 'с']:
            if is_text_widget:
                focused.event_generate("<<Copy>>")
                return "break"

        # Ctrl + X (Вирізання) - код 88
        elif event.keycode == 88 or getattr(event, 'char', '').lower() in ['x', 'ч']:
            if is_text_widget:
                focused.event_generate("<<Cut>>")
                return "break"

        # Ctrl + A (Виділити все) - код 65
        elif event.keycode == 65 or getattr(event, 'char', '').lower() in ['a', 'ф']:
            if is_text_widget:
                if isinstance(focused, (ctk.CTkEntry, tk.Entry)):
                    focused.select_range(0, 'end')
                elif isinstance(focused, (ctk.CTkTextbox, tk.Text)):
                    focused.tag_add("sel", "1.0", "end")
                return "break"

        # Ctrl + Z (Крок назад) - код 90
        elif event.keycode == 90 or getattr(event, 'char', '').lower() in ['z', 'я']:
            if is_text_widget:
                try:
                    focused.event_generate("<<Undo>>")
                except:
                    pass
                return "break"

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email, old_email, password, api_key, net_profit FROM accounts")
        for row in cursor.fetchall():
            self.tree.insert("", "end", values=(row[0], row[1], row[2], row[3], f"${row[4]}"))
        conn.close()

    def on_tree_double_click(self, event):
        selected_item = self.tree.selection()
        if selected_item:
            email = self.tree.item(selected_item[0])['values'][0]
            self.load_account_data(email)
            self.tabview.set("Деталі")

    def load_accounts_list(self):
        for widget in self.accounts_list_frame.winfo_children():
            widget.destroy()
        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM accounts")
        accounts = cursor.fetchall()
        conn.close()

        for (email,) in accounts:
            btn = ctk.CTkButton(self.accounts_list_frame, text=email, fg_color="transparent",
                                border_width=1, text_color=("gray10", "#DCE4EE"), anchor="w",
                                command=lambda e=email: self.load_account_data(e))
            btn.pack(fill="x", pady=2, padx=2)

    def open_create_dialog(self):
        dialog = ctk.CTkInputDialog(text="Введіть Email нового акаунта:", title="Новий акаунт")
        email = dialog.get_input()
        if email:
            self.fm.create_account_folder(email, STATUSES[0])
            self.db.add_account(email, "", "", "", "", STATUSES[0])
            self.load_accounts_list()
            self.load_account_data(email)
            self.show_status(f"Акаунт {email} створено!", "green")

    def load_account_data(self, email):
        self.current_account = email
        self.lbl_editing_status.configure(text=f"⚙️ Редагування: {email}")

        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT password, api_key, secret_key, old_email, status, text_notes, invested, deposit, balance, net_profit FROM accounts WHERE email=?",
            (email,))
        data = cursor.fetchone()
        conn.close()

        if data:
            self.entry_main_email.delete(0, 'end');
            self.entry_main_email.insert(0, email)
            self.entry_pass.delete(0, 'end');
            self.entry_pass.insert(0, data[0] if data[0] else "")
            self.entry_api.delete(0, 'end');
            self.entry_api.insert(0, data[1] if data[1] else "")
            self.entry_secret.delete(0, 'end');
            self.entry_secret.insert(0, data[2] if data[2] else "")
            self.entry_old_email.delete(0, 'end');
            self.entry_old_email.insert(0, data[3] if data[3] else "")
            self.status_var.set(data[4] if data[4] else STATUSES[0])

            self.text_notes.delete("0.0", "end")
            if data[5]: self.text_notes.insert("0.0", data[5])

            self.entry_invested.delete(0, 'end');
            self.entry_invested.insert(0, str(data[6]))
            self.entry_deposit.delete(0, 'end');
            self.entry_deposit.insert(0, str(data[7]))
            self.entry_balance.delete(0, 'end');
            self.entry_balance.insert(0, str(data[8]))

            color = "#00ff00" if data[9] >= 0 else "#ff4444"
            self.lbl_profit.configure(text=f"Прибуток: ${data[9]}", text_color=color)

    def save_current_account(self):
        if not self.current_account: return

        new_email = self.entry_main_email.get().strip()
        if not new_email:
            self.show_status("Головна пошта не може бути порожньою!", "red")
            return

        old_email_db = self.current_account
        status = self.status_var.get()

        if new_email != old_email_db:
            import sqlite3
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM accounts WHERE email=?", (old_email_db,))
            current_status = cursor.fetchone()[0]
            conn.close()

            success = self.fm.rename_account(old_email_db, new_email, current_status)
            if success:
                self.db.rename_email(old_email_db, new_email)
                self.current_account = new_email
                self.load_accounts_list()
            else:
                self.show_status("Помилка при перейменуванні папки!", "red")
                return

        password = self.entry_pass.get()
        api = self.entry_api.get()
        secret = self.entry_secret.get()
        old_email = self.entry_old_email.get()
        notes = self.text_notes.get("0.0", "end").strip()

        try:
            inv = float(self.entry_invested.get() or 0)
            dep = float(self.entry_deposit.get() or 0)
            balance = float(self.entry_balance.get() or 0)
        except ValueError:
            self.show_status("Помилка: У поля фінансів вводьте лише числа!", "red")
            return

        import sqlite3
        conn = sqlite3.connect(self.db.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM accounts WHERE email=?", (self.current_account,))
        old_status = cursor.fetchone()[0]
        if old_status != status:
            self.fm.move_account(self.current_account, old_status, status)

        net_profit = balance - dep - inv
        cursor.execute('''UPDATE accounts
                          SET password=?,
                              api_key=?,
                              secret_key=?,
                              old_email=?,
                              status=?,
                              text_notes=?,
                              invested=?,
                              deposit=?,
                              balance=?,
                              net_profit=?
                          WHERE email = ?''',
                       (password, api, secret, old_email, status, notes, inv, dep, balance, net_profit,
                        self.current_account))
        conn.commit()
        conn.close()

        acc_dir = BASE_DIR / status / self.current_account
        self.fm.update_info_file(acc_dir, self.current_account, old_email, password, api, secret)

        self.load_account_data(self.current_account)
        self.refresh_table()
        self.show_status("Зміни успішно збережено!", "green")

    def delete_current_account(self):
        if not self.current_account: return

        confirm_modal = ctk.CTkToplevel(self)
        confirm_modal.title("Підтвердження")
        confirm_modal.geometry("350x150")
        confirm_modal.transient(self)
        confirm_modal.grab_set()
        confirm_modal.geometry(f"+{self.winfo_x() + 350}+{self.winfo_y() + 300}")

        ctk.CTkLabel(confirm_modal,
                     text=f"Видалити акаунт {self.current_account} назавжди?\n(Папка з файлами також буде видалена)",
                     font=ctk.CTkFont(weight="bold")).pack(pady=20)

        def confirm():
            status = self.status_var.get()
            self.fm.delete_account(self.current_account, status)
            self.db.delete_account(self.current_account)
            self.current_account = None

            self.entry_main_email.delete(0, 'end')
            self.entry_pass.delete(0, 'end')
            self.text_notes.delete("0.0", "end")
            self.lbl_editing_status.configure(text="⚙️ Редагування: (не вибрано)")

            self.load_accounts_list()
            self.refresh_table()
            self.show_status("Акаунт успішно видалено!", "green")
            confirm_modal.destroy()

        btn_frame = ctk.CTkFrame(confirm_modal, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20)
        ctk.CTkButton(btn_frame, text="Ні, скасувати", command=confirm_modal.destroy, fg_color="gray").pack(side="left",
                                                                                                            padx=10)
        ctk.CTkButton(btn_frame, text="Так, видалити", command=confirm, fg_color="red", hover_color="darkred").pack(
            side="right", padx=10)

    # ================= "НАКОПИЧУВАЧ" ФАЙЛІВ ТА СКРІНІВ =================

    def open_batch_modal(self):
        if not self.current_account:
            self.show_status("Спочатку виберіть акаунт зі списку!", "red")
            return

        self.active_modal = ctk.CTkToplevel(self)
        self.active_modal.title("Накопичувач файлів")
        self.active_modal.geometry("650x600")
        self.active_modal.transient(self)
        self.active_modal.grab_set()
        self.active_modal.geometry(f"+{self.winfo_x() + 200}+{self.winfo_y() + 50}")

        def modal_universal_shortcuts(event):
            focused = self.active_modal.focus_get()
            is_text_widget = isinstance(focused, (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text))

            if event.keycode == 86 or getattr(event, 'char', '').lower() in ['v', 'м']:
                if is_text_widget:
                    focused.event_generate("<<Paste>>")
                    return "break"
                else:
                    self.add_from_clipboard_to_modal()
                    return "break"
            elif event.keycode == 67 or getattr(event, 'char', '').lower() in ['c', 'с']:
                if is_text_widget: focused.event_generate("<<Copy>>"); return "break"
            elif event.keycode == 88 or getattr(event, 'char', '').lower() in ['x', 'ч']:
                if is_text_widget: focused.event_generate("<<Cut>>"); return "break"
            elif event.keycode == 65 or getattr(event, 'char', '').lower() in ['a', 'ф']:
                if is_text_widget:
                    if isinstance(focused, (ctk.CTkEntry, tk.Entry)):
                        focused.select_range(0, 'end')
                    elif isinstance(focused, (ctk.CTkTextbox, tk.Text)):
                        focused.tag_add("sel", "1.0", "end")
                return "break"

        self.active_modal.bind("<Control-KeyPress>", modal_universal_shortcuts)

        self.active_modal.entry_widgets = []

        top_bar = ctk.CTkFrame(self.active_modal, fg_color="transparent")
        top_bar.pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(top_bar, text="📋 Вставити скріншот", command=self.add_from_clipboard_to_modal, fg_color="#b35b04",
                      hover_color="#d9710b").pack(side="left", padx=5)
        ctk.CTkButton(top_bar, text="➕ Вибрати файли з ПК", command=self.add_from_file_dialog, fg_color="#1f538d").pack(
            side="right", padx=5)

        self.active_modal.lbl_warn = ctk.CTkLabel(self.active_modal, text="", text_color="red")
        self.active_modal.lbl_warn.pack()

        self.active_modal.scroll = ctk.CTkScrollableFrame(self.active_modal, width=600, height=400)
        self.active_modal.scroll.pack(pady=5, padx=10, fill="both", expand=True)

        ctk.CTkButton(self.active_modal, text="💾 Зберегти всі файли у папку акаунта", fg_color="green",
                      hover_color="darkgreen", command=self.save_batch_action).pack(pady=15)

        self.add_from_clipboard_to_modal()

    def show_modal_warning(self, text):
        self.active_modal.lbl_warn.configure(text=text)
        self.active_modal.after(3000, lambda: self.active_modal.lbl_warn.configure(text=""))

    def render_image_row(self, img, default_name):
        frame = ctk.CTkFrame(self.active_modal.scroll, fg_color="transparent")
        frame.pack(pady=5, fill="x")

        preview_img = img.copy()
        preview_img.thumbnail((150, 100))
        ctk_img = ctk.CTkImage(light_image=preview_img, dark_image=preview_img, size=preview_img.size)

        ctk.CTkLabel(frame, image=ctk_img, text="").pack(side="left", padx=10)

        name_entry = ctk.CTkEntry(frame, width=250)
        name_entry.insert(0, default_name)
        name_entry.pack(side="left", padx=10)

        item_data = (img, name_entry)
        self.active_modal.entry_widgets.append(item_data)

        def remove_row():
            frame.destroy()
            if item_data in self.active_modal.entry_widgets:
                self.active_modal.entry_widgets.remove(item_data)

        btn_delete = ctk.CTkButton(frame, text="❌", width=30, fg_color="#8b0000", hover_color="#5c0000",
                                   command=remove_row)
        btn_delete.pack(side="right", padx=10)

    def add_from_clipboard_to_modal(self):
        try:
            img_data = ImageGrab.grabclipboard()
        except Exception as e:
            self.show_modal_warning("Помилка читання буфера обміну.")
            return

        if img_data is None:
            self.show_modal_warning("У буфері зараз немає картинки!")
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
        if not self.active_modal.entry_widgets:
            self.show_modal_warning("Спочатку додайте файли!")
            return

        status = self.status_var.get()
        acc_dir = BASE_DIR / status / self.current_account

        count = 0
        for img, entry in self.active_modal.entry_widgets:
            name = entry.get().strip()
            if not name.endswith(('.png', '.jpg', '.jpeg')):
                name += ".png"
            img.save(acc_dir / name)
            count += 1

        self.show_status(f"Успішно збережено {count} файлів!", "green")
        self.active_modal.destroy()
        self.active_modal = None

    def open_folder(self):
        if not self.current_account: return
        status = self.status_var.get()
        acc_dir = BASE_DIR / status / self.current_account
        os.startfile(acc_dir)


if __name__ == "__main__":
    app = App()
    app.mainloop()