import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from automation.scenarios.rk_navigation import RKPageStateAnalyzer
from automation.scenarios.rk_recovery import RKRecoveryMixin
from automation.scenarios.rk_documents import RKDocumentsMixin
from automation.scenarios.rk_submission import RKSubmissionMixin
from automation.scenarios.rk_validation import rejection_error, RKEmailCodeRejected, RKSubmissionRejected
from automation.scenarios.submit_mexc_risk_control import SubmitMexcRiskControlScenario
from automation.recovery import PageState
from services.rk_submission_files import upload_file_error, MAX_UPLOAD_BYTES
from services.rk_submission_journal import read_submission_state, write_submission_state, FILENAME


class ReliabilityTests(unittest.TestCase):
    def test_resource_sampling_does_not_block_scenario(self):
        import automation.resource_monitor as monitor
        entered, release = threading.Event(), threading.Event()
        def collect(**kwargs):
            self.assertIsNone(kwargs.get('driver'))
            entered.set()
            release.wait(3)
            return {}
        with patch.object(monitor, 'build_resource_snapshot', side_effect=collect), \
             patch.object(monitor, '_append_jsonl'), patch.object(monitor, '_log_summary'):
            try:
                monitor.emit_resource_event('test', task_id='nonblocking-test')
                self.assertTrue(entered.wait(2))
                # A second event is throttled even while the worker is blocked.
                monitor.emit_resource_event('test', task_id='nonblocking-test')
                self.assertEqual(monitor._PENDING.qsize(), 0)
            finally:
                release.set()
                monitor._PENDING.join()

    def test_tab_discovery_prefers_rk_without_visiting_other_tabs(self):
        driver = Mock()
        driver.window_handles = ['security', 'risk']
        driver.current_window_handle = 'security'
        driver.current_url = 'https://www.mexc.com/user/security'
        driver.execute_cdp_cmd.return_value = {'targetInfos': [
            {'targetId': 'risk', 'type': 'page', 'url': 'https://www.mexc.com/support/apply-risk-account-protection/form'}]}
        analyzer = RKPageStateAnalyzer()
        analyzer.bind(driver, Mock())
        self.assertEqual(analyzer.owned_handle, 'risk')
        driver.switch_to.window.assert_called_once_with('risk')
        driver.switch_to.new_window.assert_not_called()

    def test_closed_owned_tab_is_not_replaced(self):
        analyzer = RKPageStateAnalyzer()
        analyzer.owned_handle = 'risk'
        driver = Mock(window_handles=['other'])
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            analyzer.ensure_owned(driver)
        driver.switch_to.new_window.assert_not_called()

    def test_corrupt_journal_is_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / FILENAME).write_text('bad json')
            self.assertEqual(read_submission_state(root)['status'], 'unknown')

    def test_submission_journal_retains_uncertainty_without_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_submission_state(root, 'pending', 'task')
            self.assertEqual(read_submission_state(root)['status'], 'pending')
            write_submission_state(root, 'rejected', 'task', 'Incorrect code 123456')
            self.assertNotIn('123456', (root / FILENAME).read_text())

    def test_code_retry_only_for_explicit_code_rejection(self):
        self.assertIsInstance(rejection_error([{'field': 'emailCode', 'text': 'Invalid verification code'}]), RKEmailCodeRejected)
        self.assertNotIsInstance(rejection_error([{'text': 'Facial recognition required'}]), RKEmailCodeRejected)
        self.assertIsNone(rejection_error([]))

    def test_code_retry_is_bounded(self):
        s = SubmitMexcRiskControlScenario(None, SimpleNamespace(email='test@example.com', password=''),
            account_dir=Path('.'), address_pdf_path=None, occupation_pdf_path=None, deposit_screenshot_paths=[],
            occupation_details_text='', deposit_source_text='')
        s._request_email_code = Mock()
        s._fill_email_code = Mock()
        s._submit_application = Mock()
        s._verify_submitted = Mock(side_effect=RKEmailCodeRejected('Invalid code'))
        with patch('automation.scenarios.submit_mexc_risk_control.CheckpointRunner') as runner:
            runner.return_value.run.side_effect = RKEmailCodeRejected('Invalid code')
            with self.assertRaises(RKEmailCodeRejected):
                s._run_checkpoints()
        s._request_email_code.assert_called_once()
        s._submit_application.assert_called_once()

    def test_rejected_form_fails_immediately(self):
        helper = RKSubmissionMixin()
        helper.debug = Mock()
        helper._raise_if_cancelled = Mock()
        helper._raise_if_browser_closed = Mock()
        helper._submitted_visible = Mock(return_value=False)
        helper.driver = Mock()
        helper.driver.execute_script.return_value = [{'text': 'Facial recognition required'}]
        helper.task_id = 'test'
        with tempfile.TemporaryDirectory() as folder:
            helper.account_dir = Path(folder)
            with patch('automation.scenarios.rk_submission.time.sleep') as sleep:
                with self.assertRaises(RKSubmissionRejected):
                    helper._verify_submitted()
                sleep.assert_not_called()

    def test_recovery_retries_only_once(self):
        helper = RKRecoveryMixin()
        helper._rk_check_cancelled = Mock()
        helper._submission_attempted = False
        helper.state_analyzer = Mock()
        helper.state_analyzer.analyze.return_value = PageState('network_error', 1.0)
        helper.driver = Mock()
        helper.driver.execute_script.return_value = False
        helper.debug = Mock()
        helper.network_recovery_handler = Mock(return_value='refresh')
        helper._open_rk_form = Mock()
        helper._wait_for_rk_form = Mock()
        helper._verify_review_checks = Mock()
        action = Mock(side_effect=RuntimeError('offline'))
        with self.assertRaises(RuntimeError):
            helper._run_recoverable_step('upload', action)
        self.assertEqual(action.call_count, 2)
        helper.network_recovery_handler.assert_called_once()

    def test_successful_existing_upload_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / 'bank.pdf'
            pdf.write_bytes(b'%PDF-test')
            helper = RKDocumentsMixin()
            helper.debug = Mock()
            helper._section_file_snapshot = Mock(return_value={'fileNamesExact': ['bank.pdf'], 'confirmed': True})
            helper._send_files = Mock()
            helper._upload_optional_files(('proof of address',), [pdf], 'test')
            helper._send_files.assert_not_called()

    def test_size_limit_checked_before_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'big.pdf'
            with file.open('wb') as stream:
                stream.truncate(MAX_UPLOAD_BYTES)
            self.assertIn('10 MB', upload_file_error(file))


if __name__ == '__main__':
    unittest.main()
