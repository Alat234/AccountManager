from datetime import datetime

import customtkinter as ctk


class ActivityLogPanel(ctk.CTkFrame):
    """Compact user-facing operation log."""

    def __init__(self, parent):
        super().__init__(
            parent,
            fg_color="#050807",
            border_width=1,
            border_color="#1f6f46",
            corner_radius=8,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Журнал операцій",
            text_color="#7CFFB2",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            header,
            text="Очистити",
            width=72,
            height=24,
            fg_color="#123524",
            hover_color="#1b4f35",
            command=self.clear,
        ).grid(row=0, column=1, sticky="e")

        self.textbox = ctk.CTkTextbox(
            self,
            height=130,
            fg_color="#020403",
            text_color="#9CFFBC",
            border_width=0,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        self.textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        self.textbox.configure(state="disabled")
        self.add("Система готова до роботи.", "info")

    def add(self, message: str, level: str = "info") -> None:
        if not message:
            return
        prefix = {
            "success": "OK",
            "error": "ERR",
            "warning": "WAIT",
            "info": "RUN",
        }.get(level, "RUN")
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {prefix}  {message}\n"
        self.textbox.configure(state="normal")
        self.textbox.insert("end", line)
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
