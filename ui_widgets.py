import customtkinter as ctk
import pyotp
import time


def create_entry_with_copy(parent, copy_func, font=None):
    """Створює поле вводу, яке вміє тягнутися, разом із фіксованою кнопкою копіювання"""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.grid_columnconfigure(0, weight=1)  # ДОЗВОЛЯЄ ПОЛЮ РОЗТЯГУВАТИСЯ

    entry = ctk.CTkEntry(frame, font=font)
    entry.grid(row=0, column=0, sticky="ew")  # ew = тягнутися від лівого краю до правого

    btn_copy = ctk.CTkButton(frame, text="📋", width=28, fg_color="#343638", hover_color="#1f538d",
                             command=lambda: copy_func(entry.get()))
    btn_copy.grid(row=0, column=1, padx=(5, 0))
    return frame, entry


class TwoFactorAuthWidget(ctk.CTkFrame):
    """Окрема незалежна панель для Google Authenticator"""

    def __init__(self, master, copy_func):
        super().__init__(master, fg_color="#212121", corner_radius=10, border_width=1, border_color="#343638")
        self.copy_func = copy_func

        ctk.CTkLabel(self, text="🔐 2FA Аутентифікатор", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5))

        input_frame = ctk.CTkFrame(self, fg_color="transparent")
        input_frame.pack(pady=5, padx=10, fill="x")
        self.entry_secret = ctk.CTkEntry(input_frame, placeholder_text="Введіть 2FA Secret Key", width=180)
        self.entry_secret.pack(side="left", padx=5)

        self.lbl_code = ctk.CTkLabel(self, text="------", font=ctk.CTkFont(size=32, weight="bold", family="Courier"))
        self.lbl_code.pack(pady=(5, 0))

        self.progress = ctk.CTkProgressBar(self, width=180, progress_color="#1fa5ff")
        self.progress.set(0)
        self.progress.pack(pady=(5, 5))

        self.lbl_timer = ctk.CTkLabel(self, text="Очікування ключа...", text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_timer.pack(pady=(0, 5))

        self.btn_copy_code = ctk.CTkButton(self, text="📋 Скопіювати код", fg_color="#1f538d", hover_color="#143a63",
                                           command=self.copy_current_code)
        self.btn_copy_code.pack(pady=(0, 15))

        self.update_clock()

    def set_secret(self, secret):
        self.entry_secret.delete(0, 'end')
        if secret: self.entry_secret.insert(0, secret)
        self.update_clock()

    def get_secret(self):
        return self.entry_secret.get().strip().replace(" ", "").upper()

    def copy_current_code(self):
        code = self.lbl_code.cget("text").replace(" ", "")
        if code and code.isdigit():
            self.copy_func(code)

    def update_clock(self):
        current_secret = self.get_secret()
        if not current_secret:
            self.lbl_code.configure(text="------", text_color="gray")
            self.progress.set(0)
            self.lbl_timer.configure(text="Введіть Secret Key")
        else:
            try:
                totp = pyotp.TOTP(current_secret)
                code = totp.now()
                formatted_code = f"{code[:3]} {code[3:]}"

                time_remaining = 30 - (int(time.time()) % 30)
                progress_val = time_remaining / 30.0

                self.lbl_code.configure(text=formatted_code, text_color="white")
                self.progress.set(progress_val)

                if time_remaining <= 5:
                    self.progress.configure(progress_color="#ff4444")
                    self.lbl_code.configure(text_color="#ff4444")
                    self.lbl_timer.configure(text=f"Увага! Оновлення через {time_remaining} с", text_color="#ff4444")
                else:
                    self.progress.configure(progress_color="#00ff00")
                    self.lbl_code.configure(text_color="white")
                    self.lbl_timer.configure(text=f"Дійсний ще {time_remaining} сек", text_color="gray")
            except Exception:
                self.lbl_code.configure(text="ПОМИЛКА", text_color="#ff4444")
                self.progress.set(0)
                self.progress.configure(progress_color="#ff4444")
                self.lbl_timer.configure(text="Невірний формат ключа!", text_color="#ff4444")

        self.after(1000, self.update_clock)