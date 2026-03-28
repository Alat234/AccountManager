import customtkinter as ctk
import os
import time
from tkinter import filedialog
from PIL import ImageGrab, Image
import tkinter as tk


def open_delete_modal(parent, account_name, confirm_callback):
    """Маленьке вікно для підтвердження видалення"""
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


class BatchUploadModal(ctk.CTkToplevel):
    """Велике вікно Накопичувача файлів"""

    def __init__(self, parent, account_name, acc_dir, success_callback):
        super().__init__(parent)
        self.title(f"Накопичувач файлів для: {account_name}")
        self.geometry("650x600")
        self.transient(parent)
        self.grab_set()
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

        if event.keycode == 86 or getattr(event, 'char', '').lower() in ['v', 'м']:
            if is_text_widget:
                focused.event_generate("<<Paste>>")
            else:
                self.add_from_clipboard()
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
        for img, entry in self.entry_widgets:
            name = entry.get().strip()
            if not name.endswith(('.png', '.jpg', '.jpeg')): name += ".png"
            img.save(self.acc_dir / name)
            count += 1

        self.success_callback(count)
        self.destroy()