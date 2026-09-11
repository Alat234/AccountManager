import concurrent.futures
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from automation.base import BaseScenario, ScenarioResult
from automation.runner import ScenarioRunner
from automation.profile_access import PROFILE_ACCESS, ProfileBusyError, profile_key
from automation.operation_control import OperationControl, OperationCancelled
from automation.input_bundle import prepare_uploads
from services.task_service import TaskService
from services.operation_event_service import OperationEventService
from storage.database import DatabaseManager
from storage.task_repository import StaleTaskError


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = DatabaseManager.__new__(DatabaseManager)
        self.db.db_path = Path(self.folder.name) / 'test.db'
        self.db.init_db()
        self.service = TaskService(self.db, OperationEventService(self.db))
        self.task = self.service.create_task('example', 'risk')

    def test_stale_write_cannot_erase_submission_marker(self):
        stale = self.db.get_task(self.task.id)
        self.service.mark_external_action(self.task.id, True)
        with self.assertRaises(StaleTaskError):
            self.db.update_task(stale)
        self.assertTrue(self.db.get_task(self.task.id).external_action_pending)

    def test_concurrent_progress_preserves_marker(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.service.record_step, self.task.id, str(i)) for i in range(20)]
            futures.append(pool.submit(self.service.mark_external_action, self.task.id, True))
            for future in futures:
                future.result(5)
        task = self.db.get_task(self.task.id)
        self.assertTrue(task.external_action_pending)
        self.assertEqual(task.version, 21)

    def test_late_progress_cannot_reopen_completed_task(self):
        self.service.complete_task(self.task.id, ScenarioResult(True, 'done'))
        self.service.pause_for_user(self.task.id, 'late')
        self.service.record_step(self.task.id, 'late')
        self.service.complete_task(self.task.id, ScenarioResult(False, 'late'))
        task = self.db.get_task(self.task.id)
        self.assertEqual((task.status, task.current_step, task.result_message), ('completed', 'completed', 'done'))

    def test_unknown_result_stays_unknown(self):
        self.service.mark_external_action(self.task.id, True)
        self.service.pause_for_user(self.task.id, 'wait', resume_data={'step': 1})
        self.service.complete_task(self.task.id, ScenarioResult(False, 'uncertain', {'application_status': 'unknown'}))
        self.service.mark_retrying(self.task.id)
        self.assertEqual(self.db.get_task(self.task.id).status, 'outcome_unknown')

    def test_recovery_distinguishes_queued_and_started(self):
        running = self.service.create_task('second', 'risk')
        self.service.start_task(running.id)
        self.service.recover_interrupted_tasks()
        self.assertEqual(self.db.get_task(self.task.id).status, 'cancelled')
        self.assertEqual(self.db.get_task(running.id).status, 'outcome_unknown')

    def test_journal_survives_service_restart_and_ui_clear(self):
        events = OperationEventService(self.db)
        events.emit('saved', account_email='example', task_id=self.task.id)
        events.clear_all()
        events.clear_account('example')
        reloaded = OperationEventService(self.db)
        self.assertEqual(reloaded.recent_for_task(self.task.id)[0].message, 'saved')

    def test_direct_lookup_finds_old_task(self):
        for i in range(105):
            self.service.create_task(str(i), 'other')
        self.service.start_task(self.task.id)
        self.assertEqual(self.service.get_task(self.task.id).status, 'running')

    def test_migration_preserves_old_pending_marker(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.db.db_path)) as conn, conn:
            conn.execute("ALTER TABLE automation_tasks DROP COLUMN external_action_pending")
            conn.execute('UPDATE automation_tasks SET resume_data=? WHERE id=?',
                         (json.dumps({'external_action_pending': True}), self.task.id))
        self.db.init_db()
        self.assertTrue(self.db.get_task(self.task.id).external_action_pending)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(BaseScenario, '_log_resource_event')
        patcher.start()
        self.addCleanup(patcher.stop)

    def scenario(self, profile='one'):
        class FakeScenario(BaseScenario):
            def _start_browser(self):
                self.driver = Mock()
            def run(self):
                return ScenarioResult(True, 'done')
        return FakeScenario(Mock(), SimpleNamespace(email='test', ads_profile_id=profile))

    def test_same_profile_rejected_and_other_profile_runs(self):
        client = SimpleNamespace(base_url='http://127.0.0.1:50401')
        with PROFILE_ACCESS.hold(profile_key(client, 'one')):
            with concurrent.futures.ThreadPoolExecutor(2) as pool:
                busy = pool.submit(self.scenario('one').execute)
                free = pool.submit(self.scenario('two').execute)
                with self.assertRaises(ProfileBusyError):
                    busy.result(2)
                self.assertTrue(free.result(2).success)
        self.assertTrue(self.scenario('one').execute().success)

    def test_actual_deposit_profile_is_reserved(self):
        from automation.scenarios.mexc_deposit_screenshot import MexcDepositScreenshotScenario
        scenario = MexcDepositScreenshotScenario.__new__(MexcDepositScreenshotScenario)
        scenario.main_profile_id = 'main'
        scenario.account = SimpleNamespace(ads_profile_id='rk')
        self.assertEqual(scenario.browser_profile_id, 'main')

    def test_cleanup_error_does_not_replace_success(self):
        scenario = self.scenario()
        scenario._stop_browser = Mock(side_effect=RuntimeError('cleanup'))
        self.assertTrue(scenario.execute().success)

    def test_cancel_is_signal_only_for_deposit_scenario(self):
        from automation.scenarios.mexc_deposit_screenshot import MexcDepositScreenshotScenario
        self.assertIs(MexcDepositScreenshotScenario.cancel, BaseScenario.cancel)

    def test_cancel_does_not_interrupt_other_control(self):
        first, second = OperationControl(), OperationControl()
        first.pause()
        first.cancel()
        with self.assertRaises(OperationCancelled): first.wait(30)
        second.check()
        self.assertFalse(second.cancelled.is_set())

    def test_runner_finalizes_unhandled_exception(self):
        runner = ScenarioRunner(1)
        self.addCleanup(runner.shutdown)
        done = threading.Event()
        bad = Mock()
        bad.execute.side_effect = RuntimeError('boom')
        bad._external_action_pending = False
        runner.submit('task', bad, on_complete=lambda *_: done.set())
        self.assertTrue(done.wait(2))
        self.assertFalse(runner.get_result('task').success)

    def test_shutdown_finalizes_queued_and_running(self):
        runner = ScenarioRunner(1)
        entered, release, running_done, queued_done = (threading.Event() for _ in range(4))
        first = Mock()
        first.execute.side_effect = lambda: (entered.set(), release.wait(3), ScenarioResult(True, 'done'))[-1]
        second = Mock()
        second._external_action_pending = False
        runner.submit('first', first, lambda *_: running_done.set())
        self.assertTrue(entered.wait(2))
        runner.submit('second', second, lambda *_: queued_done.set())
        try:
            runner.shutdown()
            self.assertTrue(queued_done.wait(2))
            self.assertEqual(runner.get_result('second').data['operation_status'], 'cancelled')
            second.execute.assert_not_called()
        finally:
            release.set()
        self.assertTrue(running_done.wait(2))

    def test_callback_exception_still_releases_runner(self):
        runner = ScenarioRunner(1)
        def broken(*args): raise RuntimeError('callback')
        runner.submit('test', self.scenario(), broken)
        runner.executor.shutdown(wait=True)
        self.assertEqual(runner.active_count(), 0)
        self.assertTrue(runner.get_result('test').success)

    def test_account_is_snapshot(self):
        account = SimpleNamespace(email='test', ads_profile_id='one')
        scenario = self.scenario()
        # Verify constructor, rather than assigning to an already created scenario.
        other = type(scenario)(Mock(), account)
        account.ads_profile_id = 'changed'
        self.assertEqual(other.browser_profile_id, 'one')


class BundleTests(unittest.TestCase):
    def test_original_changes_do_not_change_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'proof.pdf'
            source.write_bytes(b'original')
            copied = prepare_uploads({'address': [source]}, root / 'inputs')['address'][0]
            source.write_bytes(b'changed')
            self.assertEqual(copied.read_bytes(), b'original')
            self.assertEqual(copied.name, source.name)

    def test_missing_document_fails_before_queue(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(FileNotFoundError):
                prepare_uploads({'address': [root / 'missing.pdf']}, root / 'inputs')
            self.assertEqual(list((root / 'inputs').iterdir()), [])


class InteractionTests(unittest.TestCase):
    def test_cancel_after_recognized_state_leaves_manual_wait(self):
        from ui.app import App
        from automation.recovery import PageState, ManualAssistAction
        recognized = threading.Event()
        cancel = threading.Event()
        state = PageState('ready', .9)
        def analyze(_):
            recognized.set()
            return state
        app = SimpleNamespace(event_service=Mock(), after=Mock())
        scenario = SimpleNamespace(account=SimpleNamespace(email='test'), task_id='t',
                                   cancel_event=cancel, driver=None,
                                   state_analyzer=SimpleNamespace(analyze=analyze))
        results = []
        worker = threading.Thread(target=lambda: results.append(
            App._manual_assist_for_scenario(app, scenario, 'step', {'ready'}, state)))
        worker.start()
        try:
            self.assertTrue(recognized.wait(2))
        finally:
            cancel.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0].action, ManualAssistAction.CANCEL)

    def test_completing_one_task_does_not_close_another_captcha(self):
        from ui.app import App
        first, second = Mock(), Mock()
        app = SimpleNamespace(_captcha_modals={'a': first, 'b': second},
                              task_service=Mock())
        app.task_service.get_task.return_value = SimpleNamespace(account_email='a')
        App._close_task_captcha(app, 'task-a')
        first.destroy.assert_called_once()
        second.destroy.assert_not_called()
