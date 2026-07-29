import customtkinter as ctk

from models.account import Account


class NotesTab:
    def __init__(self, parent, on_change=None, on_remark_save=None):
        self.on_change = on_change
        self.on_remark_save = on_remark_save
        self._current_email = None

        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        # Row 0: label + save button
        remark_header = ctk.CTkFrame(parent, fg_color="transparent")
        remark_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 2))
        remark_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(remark_header, text="AdsPower Remark:",
                     font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w")
        self.btn_save_remark = ctk.CTkButton(
            remark_header, text="Зберегти remark", width=140,
            fg_color="#1f538d", hover_color="#143a63",
            command=self._on_save_remark,
        )
        self.btn_save_remark.grid(row=0, column=1, padx=(8, 0))

        # Row 1: remark textbox
        self.text_remark = ctk.CTkTextbox(parent, height=60)
        self.text_remark.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 6))

        # Row 2: main notes (expands)
        self.text_notes = ctk.CTkTextbox(parent)
        self.text_notes.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))

        if on_change:
            self.text_notes.bind("<KeyRelease>", lambda e: on_change())

    def display(self, account: Account):
        self._current_email = account.email

        self.text_remark.delete("0.0", "end")
        if account.ads_remark:
            self.text_remark.insert("0.0", account.ads_remark)

        has_ads = bool(account.ads_profile_id)
        self.btn_save_remark.configure(state="normal" if has_ads else "disabled")

        self.text_notes.delete("0.0", "end")
        if account.text_notes:
            self.text_notes.insert("0.0", account.text_notes)

    def collect_notes(self) -> str:
        return self.text_notes.get("0.0", "end").strip()

    def collect_remark(self) -> str:
        return self.text_remark.get("0.0", "end").strip()

    def clear(self):
        self._current_email = None
        self.text_remark.delete("0.0", "end")
        self.text_notes.delete("0.0", "end")
        self.btn_save_remark.configure(state="disabled")

    def _on_save_remark(self):
        if self.on_remark_save and self._current_email:
            remark = self.collect_remark()
            self.on_remark_save(self._current_email, remark)
