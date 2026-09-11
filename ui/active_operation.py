"""Active operation view, separate from the append-only activity history."""
import time
import customtkinter as ctk

STATE_TEXT = {'queued': 'У черзі', 'running': 'Виконується',
              'paused': 'Пауза', 'pause_requested': 'Призупиняю…',
              'cancelling': 'Припиняю…'}


class ActiveOperationView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color='transparent')
        self.grid_columnconfigure(0, weight=1)
        self.label = ctk.CTkLabel(self, text='', anchor='w', justify='left')
        self.label.grid(row=0, column=0, sticky='ew')
        self.pause_button = ctk.CTkButton(self, text='Пауза', width=100)
        self.pause_button.grid(row=0, column=1, padx=4)
        self.stop_button = ctk.CTkButton(self, text='Припинити операцію', width=145,
                                       fg_color='#8b3030', hover_color='#a43c3c')
        self.stop_button.grid(row=0, column=2, padx=4)

    def update_operation(self, operation):
        scenario = operation['scenario']
        snapshot = scenario.control.snapshot()
        state = snapshot['state']
        display_state = operation.get('wait_reason') or STATE_TEXT.get(state, state)
        if state != 'running':
            display_state = STATE_TEXT.get(state, state)
        seconds = int(time.monotonic() - operation['step_at'])
        stale = int(snapshot['heartbeat_age'])
        self.label.configure(text=(f"{operation['title']} · {display_state}\n"
                                   f"{operation['step']} · {seconds} с"
                                   + (f' · відповідь worker {stale} с тому' if stale >= 5 else '')))
        self.pause_button.configure(text='Продовжити' if state in ('paused', 'pause_requested') else 'Пауза',
                                    command=scenario.resume if state in ('paused', 'pause_requested') else scenario.pause,
                                    state='disabled' if state == 'cancelling' else 'normal')
        self.stop_button.configure(command=scenario.cancel,
                                   state='disabled' if state == 'cancelling' else 'normal')


class OperationUIMixin:
    def init_operation_ui(self):
        self._active_operations = {}
        self._tab_operation_labels = {}
        self.after(250, self._tick_operations)

    def _tick_operations(self):
        for email, workspace in list(self._account_workspaces.items()):
            operation = next((op for op in self._active_operations.values() if op['email'] == email), None)
            workspace['activity_log'].set_operation(operation)
            label = self._tab_operation_labels.get(email)
            if label and label.winfo_exists():
                state = operation['scenario'].control.snapshot()['state'] if operation else ''
                waiting = bool(operation and operation.get('wait_reason'))
                label.configure(text='Ⅱ' if state in ('paused', 'pause_requested') else
                                '■' if state == 'cancelling' else '!' if waiting else '●' if operation else '',
                                text_color='#ffb547' if state != 'running' or waiting else '#7CFFB2')
        self.after(500, self._tick_operations)

    def _track_operation(self, task_id, email, title, scenario):
        self._active_operations[task_id] = dict(email=email, title=title, scenario=scenario,
                                               step='Запуск', step_at=time.monotonic())

    def _operation_progress(self, task_id, message, source=''):
        operation = self._active_operations.get(task_id)
        if operation and operation['step'] != message:
            operation.update(step=message, step_at=time.monotonic())
        if operation:
            operation['wait_reason'] = ('Очікую CAPTCHA' if 'captcha_detected' in source else
                'Очікую мережу' if 'network' in source or 'wait_for_page' in source else
                'Очікую користувача' if 'manual_assist_required' in source or 'foreground_required' in source else
                'Очікую email / таймер MEXC' if 'email' in source and ('wait' in source or 'countdown' in source) else '')
