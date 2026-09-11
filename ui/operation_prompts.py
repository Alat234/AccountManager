"""Nonmodal worker questions; pause/stop controls remain accessible."""
import threading
import time
import customtkinter as ctk


def ask_operation(app, account_email, title, message, choices, default):
    done = threading.Event()
    state = {'result': default, 'dialog': None}
    def show():
        if done.is_set() or app._ui_dispatch_closed:
            return
        dialog = ctk.CTkToplevel(app)
        state['dialog'] = dialog
        dialog.title(title)
        dialog.geometry('530x240')
        dialog.transient(app)
        ctk.CTkLabel(dialog, text=message, wraplength=490, justify='left').pack(padx=20, pady=20)
        def choose(value):
            state['result'] = value
            if value is False or value == 'cancel':
                scenario = next((s for s in list(app._task_scenarios.values()) if s.account.email == account_email), None)
                if scenario:
                    scenario.cancel()
            done.set()
            dialog.destroy()
            state['dialog'] = None
        buttons = ctk.CTkFrame(dialog, fg_color='transparent')
        buttons.pack(padx=15, pady=15)
        for label, value in choices:
            ctk.CTkButton(buttons, text=label, width=145,
                          command=lambda value=value: choose(value)).pack(side='left', padx=4)
        dialog.protocol('WM_DELETE_WINDOW', lambda: choose(default))
    app.after(0, show)
    deadline = time.monotonic() + 600
    try:
        while not done.wait(.2):
            if app._ui_dispatch_closed or time.monotonic() >= deadline:
                return default
            scenario = next((s for s in list(app._task_scenarios.values()) if s.account.email == account_email), None)
            if scenario:
                scenario.control.check()
        return state['result']
    finally:
        done.set()
        app.after(0, lambda: state['dialog'] and state['dialog'].destroy())
