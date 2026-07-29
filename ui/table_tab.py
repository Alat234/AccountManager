from tkinter import ttk

from services.account_service import AccountService

COLUMN_DEFS = [
    {"id": "email",     "label": "Пошта",       "width": 180, "visible": True},
    {"id": "old_email", "label": "Стара пошта", "width": 140, "visible": True},
    {"id": "pass",      "label": "Пароль",      "width": 100, "visible": True},
    {"id": "api",       "label": "API Key",     "width": 130, "visible": True},
    {"id": "profit",    "label": "Прибуток",    "width": 90,  "visible": True, "anchor": "center"},
]


class TableTab:
    def __init__(self, parent, account_service: AccountService, on_double_click=None):
        self.parent = parent
        self.account_service = account_service
        self.on_double_click = on_double_click

        self._build(parent)

    def _build(self, parent_frame):
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#2b2b2b", foreground="white", rowheight=30,
                        fieldbackground="#2b2b2b", borderwidth=0)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#343638", foreground="white", relief="flat",
                        font=('Helvetica', 10, 'bold'))

        visible = [c for c in COLUMN_DEFS if c["visible"]]
        col_ids = [c["id"] for c in visible]

        self.tree = ttk.Treeview(parent_frame, columns=col_ids, show="headings")
        for c in visible:
            self.tree.heading(c["id"], text=c["label"])
            self.tree.column(c["id"], width=c["width"], anchor=c.get("anchor", "w"))

        vsb = ttk.Scrollbar(parent_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(parent_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        parent_frame.grid_columnconfigure(0, weight=1)
        parent_frame.grid_rowconfigure(0, weight=1)

        self.tree.bind("<Double-1>", self._on_double_click)

    def _on_double_click(self, event):
        selected_item = self.tree.selection()
        if selected_item and self.on_double_click:
            email = self.tree.item(selected_item[0])['values'][0]
            self.on_double_click(email)

    def refresh(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.account_service.get_accounts_for_table():
            self.tree.insert("", "end", values=(row[0], row[1], row[2], row[3], f"${row[4]}"))
