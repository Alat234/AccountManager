"""Atomic task changes and optimistic protection for legacy full-object writes."""
from dataclasses import fields
from datetime import datetime
import sqlite3
from contextlib import closing
from models.task import AutomationTask


class StaleTaskError(RuntimeError):
    pass


class TaskRepositoryMixin:
    @staticmethod
    def _task_from_row(row):
        values = dict(row)
        for name in ('created_at', 'completed_at'):
            values[name] = datetime.fromisoformat(values[name]) if values[name] else None
        for name in ('recoverable', 'requires_user_confirmation', 'external_action_pending'):
            values[name] = bool(values.get(name, False))
        return AutomationTask(**{f.name: values[f.name] for f in fields(AutomationTask) if f.name in values})

    def get_task(self, task_id):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM automation_tasks WHERE id=?', (task_id,)).fetchone()
            return self._task_from_row(row) if row else None

    @staticmethod
    def _write_task(conn, task):
        names = ('status', 'completed_at', 'result_message', 'result_data', 'current_step',
                 'last_error', 'retry_count', 'recoverable', 'requires_user_confirmation',
                 'resume_data', 'external_action_pending')
        values = [getattr(task, name) for name in names]
        values[1] = task.completed_at.isoformat() if task.completed_at else None
        updated = conn.execute('UPDATE automation_tasks SET ' + ','.join(name + '=?' for name in names)
                               + ', version=version+1 WHERE id=? AND version=?',
                               (*values, task.id, task.version))
        if updated.rowcount != 1:
            raise StaleTaskError('Task changed since it was read')
        task.version += 1

    def update_task(self, task):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
            self._write_task(conn, task)

    def mutate_task(self, task_id, change):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM automation_tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise LookupError('Task not found')
            task = self._task_from_row(row)
            if change(task) is False:
                return None
            self._write_task(conn, task)
            return task

    def get_unfinished_tasks(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM automation_tasks WHERE status IN ('pending','running','retrying','waiting_user','paused')").fetchall()
            return [self._task_from_row(row) for row in rows]
