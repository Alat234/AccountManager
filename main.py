import customtkinter as ctk
import os
import tkinter as tk
from tkinter import ttk

# Імпортуємо всі наші модулі!
from core import FileManager, DatabaseManager, STATUSES, BASE_DIR
from ui_widgets import create_entry_with_copy, TwoFactorAuthWidget
from modals import open_delete_modal, BatchUploadModal

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Accounts Manager CRM")
        self.geometry("1200x800")

        self.fm = FileManager()
        self.db = DatabaseManager()
        self.current_account = None

        self.setup_ui()
        self.load_accounts_list()
        self.refresh_table()

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

        self.tabview = ctk.CTkTabview(self.right_frame, command=self.on_tab_change)
        self.tabview.grid(row=0, column=0, sticky="nsew")

        tab_main = self.tabview.add("Деталі")
        tab_notes = self.tabview.add("Нотатки")
        tab_table = self.tabview.add("Таблиця (База)")

        # --- ВКЛАДКА 1: ДЕТАЛІ ---
        self.lbl_editing_status = ctk.CTkLabel(tab_main, text="⚙️ Редагування: (не вибрано)",
                                               font=ctk.CTkFont(size=22, weight="bold"), text_color="#1fa5ff")
        self.lbl_editing_status.pack(pady=(10, 0))

        info_frame = ctk.CTkFrame(tab_main, fg_color="transparent")
        info_frame.pack(fill="x", pady=10, padx=10)

        # МАГІЯ МАСШТАБУВАННЯ: Даємо 3 колонкам вагу (weight=1), щоб вони ділили екран порівну
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)
        info_frame.grid_columnconfigure(2, weight=1)
        info_frame.grid_columnconfigure(3, weight=0)  # 2FA колонка фіксована

        ctk.CTkLabel(info_frame, text="Головна пошта:", text_color="gray").grid(row=0, column=0, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Стара пошта:", text_color="gray").grid(row=0, column=1, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Пароль:", text_color="gray").grid(row=0, column=2, sticky="w", padx=5)

        # sticky="ew" розтягує поле від краю до краю своєї колонки
        frame_main_email, self.entry_main_email = create_entry_with_copy(info_frame, self.copy_to_clipboard,
                                                                         font=ctk.CTkFont(weight="bold"))
        frame_main_email.grid(row=1, column=0, padx=5, pady=(0, 15), sticky="ew")

        frame_old_email, self.entry_old_email = create_entry_with_copy(info_frame, self.copy_to_clipboard)
        frame_old_email.grid(row=1, column=1, padx=5, pady=(0, 15), sticky="ew")

        frame_pass, self.entry_pass = create_entry_with_copy(info_frame, self.copy_to_clipboard)
        frame_pass.grid(row=1, column=2, padx=5, pady=(0, 15), sticky="ew")

        ctk.CTkLabel(info_frame, text="API Key:", text_color="gray").grid(row=2, column=0, sticky="w", padx=5)
        ctk.CTkLabel(info_frame, text="Secret Key (Термінал):", text_color="gray").grid(row=2, column=1, sticky="w",
                                                                                        padx=5)
        ctk.CTkLabel(info_frame, text="Статус:", text_color="gray").grid(row=2, column=2, sticky="w", padx=5)

        frame_api, self.entry_api = create_entry_with_copy(info_frame, self.copy_to_clipboard)
        frame_api.grid(row=3, column=0, padx=5, pady=(0, 15), sticky="ew")

        frame_secret, self.entry_secret = create_entry_with_copy(info_frame, self.copy_to_clipboard)
        frame_secret.grid(row=3, column=1, padx=5, pady=(0, 15), sticky="ew")

        self.status_var = ctk.StringVar(value=STATUSES[0])
        self.opt_status = ctk.CTkOptionMenu(info_frame, values=STATUSES, variable=self.status_var)
        self.opt_status.grid(row=3, column=2, padx=5, pady=(0, 15), sticky="ew")

        # 2FA Віджет (Справа)
        self.two_fa_widget = TwoFactorAuthWidget(info_frame, self.copy_to_clipboard)
        self.two_fa_widget.grid(row=0, column=3, rowspan=4, padx=(20, 0), sticky="nsew")

        # Фінанси
        fin_frame = ctk.CTkFrame(tab_main)
        fin_frame.pack(fill="x", pady=10, padx=10)

        # МАГІЯ МАСШТАБУВАННЯ ДЛЯ ФІНАНСІВ
        fin_frame.grid_columnconfigure((0, 1, 2), weight=1)
        fin_frame.grid_columnconfigure(3, weight=0)

        ctk.CTkLabel(fin_frame, text="Вкладено ($):", text_color="gray").grid(row=0, column=0, sticky="w", padx=10,
                                                                              pady=(5, 0))
        ctk.CTkLabel(fin_frame, text="Депозит ($):", text_color="gray").grid(row=0, column=1, sticky="w", padx=10,
                                                                             pady=(5, 0))
        ctk.CTkLabel(fin_frame, text="Баланс ($):", text_color="gray").grid(row=0, column=2, sticky="w", padx=10,
                                                                            pady=(5, 0))

        self.entry_invested = ctk.CTkEntry(fin_frame)
        self.entry_invested.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")

        self.entry_deposit = ctk.CTkEntry(fin_frame)
        self.entry_deposit.grid(row=1, column=1, padx=10, pady=(0, 10), sticky="ew")

        self.entry_balance = ctk.CTkEntry(fin_frame)
        self.entry_balance.grid(row=1, column=2, padx=10, pady=(0, 10), sticky="ew")

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

        self.bind("<Control-KeyPress>", self.handle_universal_shortcuts)

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
        focused = self.focus_get()
        is_text_widget = isinstance(focused, (ctk.CTkEntry, ctk.CTkTextbox, tk.Entry, tk.Text))

        if event.keycode == 86 or getattr(event, 'char', '').lower() in ['v', 'м']:
            if is_text_widget:
                focused.event_generate("<<Paste>>")
                return "break"
            else:
                if self.tabview.get() != "Таблиця (База)": self.open_batch_modal()
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
            self.db.add_account(email, "", "", "", "", "", STATUSES[0])
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
            "SELECT password, api_key, secret_key, two_fa_secret, old_email, status, text_notes, invested, deposit, balance, net_profit FROM accounts WHERE email=?",
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

            self.two_fa_widget.set_secret(data[3] if data[3] else "")

            self.entry_old_email.delete(0, 'end');
            self.entry_old_email.insert(0, data[4] if data[4] else "")
            self.status_var.set(data[5] if data[5] else STATUSES[0])

            self.text_notes.delete("0.0", "end")
            if data[6]: self.text_notes.insert("0.0", data[6])

            self.entry_invested.delete(0, 'end');
            self.entry_invested.insert(0, str(data[7]))
            self.entry_deposit.delete(0, 'end');
            self.entry_deposit.insert(0, str(data[8]))
            self.entry_balance.delete(0, 'end');
            self.entry_balance.insert(0, str(data[9]))

            color = "#00ff00" if data[10] >= 0 else "#ff4444"
            self.lbl_profit.configure(text=f"Прибуток: ${data[10]}", text_color=color)

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
        two_fa = self.two_fa_widget.get_secret()
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
                              two_fa_secret=?,
                              old_email=?,
                              status=?,
                              text_notes=?,
                              invested=?,
                              deposit=?,
                              balance=?,
                              net_profit=?
                          WHERE email = ?''',
                       (password, api, secret, two_fa, old_email, status, notes, inv, dep, balance, net_profit,
                        self.current_account))
        conn.commit()
        conn.close()

        acc_dir = BASE_DIR / status / self.current_account
        self.fm.update_info_file(acc_dir, self.current_account, old_email, password, api, secret, two_fa)

        self.load_account_data(self.current_account)
        self.refresh_table()
        self.show_status("Зміни успішно збережено!", "green")

    # ВИТЯГНУТІ ФУНКЦІЇ У ФАЙЛ MODALS.PY ВІДПРАЦЬОВУЮТЬ ТУТ:

    def delete_current_account(self):
        if not self.current_account: return

        def on_confirm():
            status = self.status_var.get()
            self.fm.delete_account(self.current_account, status)
            self.db.delete_account(self.current_account)
            self.current_account = None

            self.entry_main_email.delete(0, 'end')
            self.entry_pass.delete(0, 'end')
            self.text_notes.delete("0.0", "end")
            self.two_fa_widget.set_secret("")
            self.lbl_editing_status.configure(text="⚙️ Редагування: (не вибрано)")

            self.load_accounts_list()
            self.refresh_table()
            self.show_status("Акаунт успішно видалено!", "green")

        open_delete_modal(self, self.current_account, on_confirm)

    def open_batch_modal(self):
        if not self.current_account:
            self.show_status("Спочатку виберіть акаунт зі списку!", "red")
            return

        status = self.status_var.get()
        acc_dir = BASE_DIR / status / self.current_account

        def on_success(count):
            self.show_status(f"Успішно збережено {count} файлів!", "green")

        BatchUploadModal(self, self.current_account, acc_dir, on_success)

    def open_folder(self):
        if not self.current_account: return
        status = self.status_var.get()
        acc_dir = BASE_DIR / status / self.current_account
        os.startfile(acc_dir)


if __name__ == "__main__":
    app = App()
    app.mainloop()