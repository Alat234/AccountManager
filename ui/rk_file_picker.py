"""Review ambiguous RK document choices before starting a browser."""
import tkinter as tk
import customtkinter as ctk
from services.rk_submission_files import RKFileChoices, submission_files


class RKFilePicker(ctk.CTkToplevel):
    def __init__(self, parent, choices: RKFileChoices):
        super().__init__(parent)
        self.title('Submit RK — вибір документів')
        self.geometry('740x520')
        self.transient(parent)
        self.result = None
        self.choices = choices
        self.pdfs = []
        body = ctk.CTkScrollableFrame(self)
        body.pack(fill='both', expand=True, padx=12, pady=12)
        ctk.CTkLabel(body, text='Оберіть PDF: усі вибрані файли будуть додані в обидві секції').pack(anchor='w')
        for path in choices.pdfs:
            selected = tk.BooleanVar(value=len(choices.pdfs) == 1)
            self.pdfs.append((path, selected))
            ctk.CTkCheckBox(body, text=path.name, variable=selected).pack(anchor='w', pady=5)
        ctk.CTkLabel(body, text='Оберіть 1–2 скриншоти депозитів').pack(anchor='w', pady=(16, 4))
        self.images = []
        for path in choices.screenshots:
            selected = tk.BooleanVar(value=len(choices.screenshots) <= 2)
            self.images.append((path, selected))
            ctk.CTkCheckBox(body, text=path.name, variable=selected).pack(anchor='w', pady=5)
        self.error = ctk.CTkLabel(self, text='', text_color='#ff9800')
        self.error.pack()
        buttons = ctk.CTkFrame(self, fg_color='transparent')
        buttons.pack(fill='x', padx=12, pady=12)
        ctk.CTkButton(buttons, text='Скасувати', command=self.destroy).pack(side='left')
        ctk.CTkButton(buttons, text='Продовжити', command=self._confirm).pack(side='right')
        self.after(100, self.grab_set)

    def _confirm(self):
        pdfs = [p for p, selected in self.pdfs if selected.get()]
        images = [p for p, selected in self.images if selected.get()]
        if self.choices.pdfs and not pdfs:
            self.error.configure(text='Оберіть щонайменше один PDF.')
            return
        if self.choices.screenshots and not 1 <= len(images) <= 2:
            self.error.configure(text='Потрібно обрати один або два скриншоти.')
            return
        try:
            self.result = submission_files(pdfs, images)
        except OSError:
            self.error.configure(text='Не вдалося прочитати вибрані файли. Перевірте папку акаунта.')
            return
        if self.result.get('invalid'):
            self.error.configure(text='\n'.join(self.result['invalid']))
            self.result = None
            return
        self.destroy()


def choose_rk_files(parent, choices: RKFileChoices):
    dialog = RKFilePicker(parent, choices)
    parent.wait_window(dialog)
    return dialog.result
