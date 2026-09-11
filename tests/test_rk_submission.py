import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

from services.rk_submission_files import discover_rk_files, submission_files
from automation.scenarios.rk_documents import RKDocumentsMixin, uploads_confirmed
from automation.scenarios.rk_review_checks import REVIEW_CHECKS_SCRIPT, require_review_checks
from automation.scenarios.rk_dropdown import RKDropdown
from automation.scenarios.submit_mexc_risk_control import SubmitMexcRiskControlScenario
from automation.scenarios.mexc_state import MexcPageStateAnalyzer
from models.rk_document_types import (
    ADDRESS_DOCUMENT_TYPES, DEPOSIT_SOURCE_TYPES, DEFAULT_ADDRESS_TYPE,
    DEFAULT_DEPOSIT_SOURCE_TYPE, normalized_category,
)


class LocalPreflightTests(unittest.TestCase):
    def test_legacy_source_category_is_repaired(self):
        for old in ("Other Document", DEFAULT_ADDRESS_TYPE, "", None):
            self.assertEqual(normalized_category(old, DEPOSIT_SOURCE_TYPES, DEFAULT_DEPOSIT_SOURCE_TYPE),
                             DEFAULT_DEPOSIT_SOURCE_TYPE)
        self.assertEqual(normalized_category("Funds From Third-Party Transfers", DEPOSIT_SOURCE_TYPES,
                                            DEFAULT_DEPOSIT_SOURCE_TYPE), "Funds From Third-Party Transfers")

    def test_document_categories_are_separate(self):
        self.assertFalse(set(ADDRESS_DOCUMENT_TYPES) & set(DEPOSIT_SOURCE_TYPES))
        self.assertEqual(normalized_category("Other Document", ADDRESS_DOCUMENT_TYPES, DEFAULT_ADDRESS_TYPE),
                         "Other Document")

    def test_scenario_uses_configured_categories(self):
        scenario = SubmitMexcRiskControlScenario(
            None, SimpleNamespace(email='test@example.com', password=''), account_dir=Path('.'),
            address_pdf_path=None, occupation_pdf_path=None, deposit_screenshot_paths=[],
            occupation_details_text='', deposit_source_text='',
            address_document_type_text=ADDRESS_DOCUMENT_TYPES[2],
            deposit_source_type_text=DEPOSIT_SOURCE_TYPES[1],
        )
        with patch('automation.scenarios.submit_mexc_risk_control.RKDropdown') as dropdown:
            scenario._select_proof_of_address_type()
            scenario._select_deposit_source_type()
            self.assertEqual(dropdown.return_value.select.call_args_list[0].args[1], ADDRESS_DOCUMENT_TYPES[2])
            self.assertEqual(dropdown.return_value.select.call_args_list[1].args[1], DEPOSIT_SOURCE_TYPES[1])

    def test_discovery_and_ambiguous_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['a.PDF', 'b.pdf', 'rk_deposit_a.png', 'rk_deposit_b.jpg', 'rk_deposit_c.png', 'screen.png']:
                (root / name).write_bytes(b'document')
            choices = discover_rk_files(root)
            self.assertEqual(len(choices.pdfs), 2)
            self.assertEqual(len(choices.screenshots), 4)
            self.assertIn(root / 'screen.png', choices.screenshots)
            with self.assertRaises(ValueError):
                submission_files(choices.pdfs[0], list(choices.screenshots))

    def test_multiple_pdfs_are_preserved_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            pdfs = [Path(folder) / f'bank{i}.pdf' for i in range(3)]
            for p in pdfs:
                p.write_bytes(b'%PDF-test')
            result = submission_files(pdfs + [pdfs[0]], [])
            self.assertEqual(result['bank_statement_paths'], pdfs)
            scenario = SubmitMexcRiskControlScenario(
                None, SimpleNamespace(email='test@example.com', password=''), account_dir=Path(folder),
                address_pdf_paths=pdfs, occupation_pdf_paths=pdfs, deposit_screenshot_paths=[],
                occupation_details_text='', deposit_source_text='')
            self.assertEqual(scenario.address_pdf_paths, pdfs)
            self.assertEqual(scenario.occupation_pdf_paths, pdfs)
            helper = RKDocumentsMixin()
            helper.debug = Mock()
            helper._section_file_snapshot = Mock(return_value={})
            element = Mock()
            element.get_attribute.return_value = None
            helper._wait_for_file_input_for_section = Mock(return_value=element)
            helper._send_files = Mock()
            helper._wait_for_section_uploads = Mock(return_value=True)
            helper._upload_optional_files(('occupation details',), pdfs, 'test')
            self.assertEqual([call.args[1] for call in helper._send_files.call_args_list], [[p] for p in pdfs])
            self.assertEqual(helper._wait_for_section_uploads.call_args.args[1], pdfs)

    def test_missing_documents(self):
        result = submission_files(None, [])
        self.assertEqual(len(result['missing']), 2)

    def test_empty_files_are_reported_and_not_uploaded(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / 'bank.pdf'
            pdf.touch()
            result = submission_files(pdf, [])
            self.assertIsNone(result['bank_statement_path'])
            self.assertTrue(any('empty' in item for item in result['missing']))

    def test_missing_facescan_is_a_hard_stop(self):
        for facial in [{}, {'found': True, 'checked': False},
                       {'found': True, 'checked': True, 'hasStartButton': True}]:
            with self.subTest(facial=facial), self.assertRaises(RuntimeError):
                require_review_checks({'facial': facial})

    def test_passed_facescan_and_kyc(self):
        require_review_checks({'facial': {'found': True, 'checked': True},
                               'kyc': {'found': True, 'checked': True}})

    def test_disabled_facescan_allows_missing_or_incomplete_marker(self):
        for facial in [{}, {'found': True, 'checked': False, 'hasStartButton': True}]:
            require_review_checks({'facial': facial}, enforce_facescan=False)

    def test_disabled_facescan_does_not_disable_kyc(self):
        with self.assertRaises(RuntimeError):
            require_review_checks({'kyc': {'found': True, 'checked': False}}, enforce_facescan=False)

    def test_two_screenshots_need_two_full_names(self):
        paths = [Path('rk_deposit_2026-09-01_1.png'), Path('rk_deposit_2026-09-01_2.png')]
        snapshot = {'confirmed': True, 'fileNamesExact': [paths[0].name]}
        self.assertFalse(uploads_confirmed(snapshot, paths))
        snapshot['fileNamesExact'].append(paths[1].name)
        self.assertTrue(uploads_confirmed(snapshot, paths))
        for flag in ['pending', 'uploadError']:
            self.assertFalse(uploads_confirmed({**snapshot, flag: True}, paths))

    def test_missing_facescan_section_waits_for_render(self):
        scenario = SubmitMexcRiskControlScenario(
            None, SimpleNamespace(email='test@example.com', password=''), account_dir=Path('.'),
            address_pdf_path=None, occupation_pdf_path=None, deposit_screenshot_paths=[],
            occupation_details_text='', deposit_source_text='',
        )
        scenario.driver = Mock()
        scenario.debug = Mock()
        scenario._raise_if_cancelled = Mock()
        scenario._raise_if_browser_closed = Mock()
        scenario.driver.execute_script.side_effect = [
            {'facial': {'found': False}}, {'facial': {'found': True, 'checked': True}}]
        with patch.object(scenario.control, 'wait') as sleep:
            scenario._verify_review_checks()
        sleep.assert_called_once()

    def test_submission_rechecks_facescan_before_click(self):
        scenario = SubmitMexcRiskControlScenario(
            None, SimpleNamespace(email='test@example.com', password=''), account_dir=Path('.'),
            address_pdf_path=None, occupation_pdf_path=None, deposit_screenshot_paths=[],
            occupation_details_text='', deposit_source_text='',
        )
        scenario.driver = Mock()
        scenario._verify_review_checks = Mock(side_effect=RuntimeError('Facescan missing'))
        with self.assertRaises(RuntimeError):
            scenario._submit_application()
        scenario.driver.execute_script.assert_not_called()


@unittest.skipUnless(os.environ.get('RK_TEST_CHROMEDRIVER'), 'Set RK_TEST_CHROMEDRIVER for isolated browser regression tests')
class BrowserRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        options = Options()
        if os.environ.get('RK_TEST_CHROME'):
            options.binary_location = os.environ['RK_TEST_CHROME']
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-first-run')
        cls.driver = webdriver.Chrome(service=Service(os.environ['RK_TEST_CHROMEDRIVER']), options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def page(self, html):
        self.driver.get('data:text/html;charset=utf-8,' + quote('<style>label,span,svg{display:inline-block;min-height:20px}svg{width:20px}</style>' + html))

    def test_instruction_and_nearby_kyc_do_not_pass_facescan(self):
        self.page('''<div class="fileWrapper"><label>Complete Facial Recognition</label><button>Start</button></div>
          <div class="fileWrapper"><label>Complete Advanced KYC Verification</label>
          <span class="ant-tag-v2-success"><svg data-icon="CheckCircleFilled"></svg>Completed</span></div>''')
        result = self.driver.execute_script(REVIEW_CHECKS_SCRIPT)
        self.assertFalse(result['facial']['checked'])
        self.assertTrue(result['kyc']['checked'])
        with self.assertRaises(RuntimeError):
            require_review_checks(result)

    def test_upload_above_label_stays_in_its_dom_section(self):
        self.page('''<div class="fileWrapper"><label>Proof of Address</label>
          <input id="address" type="file"></div>
          <div class="fileWrapper" style="display:flex;align-items:center;height:250px">
          <label style="margin-top:100px">Occupation Details</label>
          <div class="ant-form-item-has-success"><ul><li class="fileList"><span>bank.pdf</span></li></ul>
          <input id="occupation" type="file"><textarea id="occupationText"></textarea></div></div>''')
        helper = RKDocumentsMixin()
        helper.driver = self.driver
        snapshot = helper._section_file_snapshot(('occupation details',))
        self.assertTrue(uploads_confirmed(snapshot, [Path('bank.pdf')]), snapshot)
        self.assertEqual(helper._find_file_input_for_section(('occupation details',)).get_attribute('id'), 'occupation')
        self.assertEqual(helper._find_text_input_for_section(('occupation details',)).get_attribute('id'), 'occupationText')
        self.assertNotIn('bank.pdf', helper._section_file_snapshot(('proof of address',)).get('fileNamesExact', []))

    def test_mexc_submit_item_contains_upload_and_text_siblings(self):
        self.page('''<div class="styles__submitItem"><div class="ant-form-item styles__descLabel">
          <div class="ant-row"><div class="ant-col"><label>Occupation Details</label></div></div></div>
          <div class="ant-form-item ant-form-item-has-success" style="position:relative;top:-30px">
          <ul><li class="components__fileList"><span>bank.pdf</span></li></ul>
          <input id="occupationUpload" type="file"></div>
          <div class="ant-form-item"><textarea id="occupationText"></textarea></div></div>
          <div class="styles__submitItem"><label>Proof of Source of Last 1-2 Deposits</label>
          <input id="depositUpload" type="file"><textarea id="depositText"></textarea></div>''')
        helper = RKDocumentsMixin()
        helper.driver = self.driver
        helper.debug = Mock()
        helper._raise_if_cancelled = Mock()
        helper._raise_if_browser_closed = Mock()
        self.assertTrue(uploads_confirmed(helper._section_file_snapshot(('occupation details',)), [Path('bank.pdf')]))
        self.assertEqual(helper._find_file_input_for_section(('occupation details',)).get_attribute('id'), 'occupationUpload')
        helper._fill_section_text(('occupation details',), 'Occupation explanation', 'test')
        helper._fill_section_text(('proof of source of last',), 'Deposit explanation', 'test')
        self.assertEqual(self.driver.find_element('id', 'occupationText').get_attribute('value'), 'Occupation explanation')
        self.assertEqual(self.driver.find_element('id', 'depositText').get_attribute('value'), 'Deposit explanation')
        self.assertNotIn('bank.pdf', helper._section_file_snapshot(('proof of source of last',)).get('fileNamesExact', []))

    def test_get_code_targets_child_handler_not_suffix(self):
        from automation.scenarios.rk_email import RKEmailMixin
        helper = RKEmailMixin()
        helper.driver = self.driver
        self.page('''<span class="ant-input-affix-wrapper"><input id="emailCode">
          <span class="ant-input-suffix"><div><div><span id="link" onclick="this.textContent='60s'">Get Code</span></div></div></span></span>''')
        element = helper._find_rk_get_code_element()
        self.assertEqual(element.get_attribute('id'), 'link')
        self.driver.execute_script('arguments[0].click()', element)
        self.assertTrue(helper._email_code_request_started())

    def test_final_confirmation_clicks_only_modal_once(self):
        from automation.scenarios.rk_submission import RKSubmissionMixin
        self.page('''<button onclick="window.wrong=true">Submit Application</button>
          <div role="dialog"><h3>Confirm Application Details</h3>
          <button>Back to Edit</button><button onclick="window.count=(window.count||0)+1">Submit Application</button></div>''')
        helper = RKSubmissionMixin()
        helper.driver = self.driver
        helper.debug = Mock()
        helper._raise_if_cancelled = Mock()
        self.assertTrue(helper._confirm_application_details())
        self.assertFalse(helper._confirm_application_details())
        self.assertEqual(self.driver.execute_script('return window.count'), 1)
        self.assertFalse(self.driver.execute_script('return !!window.wrong'))

    def test_confirmation_is_not_receipt_and_hidden_dialog_is_ignored(self):
        from automation.scenarios.rk_confirmation import CONFIRMATION_BUTTON
        self.page('''<div role="dialog" style="display:none"><h3>Confirm Application Details</h3>
          <button>Submit Application</button></div><button>Submit Application</button>''')
        self.assertIsNone(self.driver.execute_script(CONFIRMATION_BUTTON))
        state = self.state_for('/support/apply-risk-account-protection/form',
            '<input id="emailCode"><div role="dialog"><h3>Confirm Application Details</h3><button>Submit Application</button></div>')
        self.assertNotEqual(state, 'risk_control_submitted')

    def test_document_rejection_reports_reason_without_code_retry(self):
        from automation.scenarios.rk_validation import VALIDATION_ERRORS, rejection_error, RKEmailCodeRejected
        self.page('<div role="dialog"><h3>Documents rejected</h3><p>Bank statement is unreadable.</p></div>')
        error = rejection_error(self.driver.execute_script(VALIDATION_ERRORS))
        self.assertIsNotNone(error)
        self.assertNotIsInstance(error, RKEmailCodeRejected)
        self.assertIn('unreadable', str(error))
        self.page('<p>Your documents may be rejected if incomplete.</p>')
        self.assertIsNone(rejection_error(self.driver.execute_script(VALIDATION_ERRORS)))

    def test_positive_facescan_marker(self):
        self.page('''<div class="fileWrapper"><label>Complete Facial Recognition</label>
          <span class="ant-tag-v2-success"><svg data-icon="CheckCircleFilled"></svg>Completed</span></div>''')
        require_review_checks(self.driver.execute_script(REVIEW_CHECKS_SCRIPT))

    def test_email_countdown_is_not_confused_with_resend_button(self):
        from automation.scenarios.rk_email import RKEmailMixin
        helper = RKEmailMixin()
        helper.driver = self.driver
        self.page('<span class="ant-input-affix-wrapper"><input id="emailCode"><span class="ant-input-suffix">23s</span></span>')
        self.assertTrue(helper._email_code_request_started())
        self.driver.execute_script("document.querySelector('.ant-input-suffix').textContent='Resend'")
        self.assertFalse(helper._email_code_request_started())

    def test_scoped_dropdown_opens_above_select(self):
        self.page('''<div class="ant-select-v2" style="margin-top:240px;width:400px">
          <div class="ant-select-v2-selector" onclick="document.getElementById('popup').style.display='block'; document.getElementById('rk').setAttribute('aria-expanded','true')">
          <span class="ant-select-v2-selection-search"><input id="rk" role="combobox" aria-controls="rk_list" style="opacity:0"></span>
          <span class="ant-select-v2-selection-placeholder">Please select</span></div></div>
          <div class="ant-select-v2-dropdown" style="position:absolute;top:0">Nationality<div class="ant-select-v2-item-option">Other Document</div></div>
          <div id="popup" class="ant-select-v2-dropdown" style="display:none;position:absolute;top:120px;width:400px">
          <div id="rk_list" role="listbox" style="height:0;overflow:hidden"></div>
          <div class="ant-select-v2-item-option">Utility Bill</div>
          <div class="ant-select-v2-item-option" onclick="document.querySelector('.ant-select-v2-selection-placeholder').className='ant-select-v2-selection-item';document.querySelector('.ant-select-v2-selection-item').textContent=this.textContent;document.getElementById('popup').style.display='none'">Bank, Credit Card &amp; Financial Statements</div></div>''')
        selected = RKDropdown(self.driver, lambda: None, Mock()).select('rk', 'Bank, Credit Card & Financial Statements', 'test')
        self.assertEqual(selected, 'bank, credit card & financial statements')

    def test_uploads_are_scoped_to_their_section(self):
        self.page('''<div><label>Proof of Address</label><div class="ant-form-item-has-success"><ul>
          <li class="fileList"><span>bank.pdf</span></li></ul></div></div>
          <div><label>Occupation Details</label><div class="ant-form-item-has-success"><ul>
          <li class="fileList"><span>bank.pdf</span></li></ul></div></div>
          <div><label>Proof of Source of Last 1-2 Deposits</label><div class="ant-form-item-has-success"><ul>
          <li class="fileList"><span>rk_deposit_a.png</span></li><li class="fileList"><span>rk_deposit_b.png</span></li></ul></div></div>
          <label>Email Verification Code</label><input id="emailCode">''')
        helper = RKDocumentsMixin()
        helper.driver = self.driver
        address = helper._section_file_snapshot(('proof of address',))
        deposits = helper._section_file_snapshot(('proof of source of last',))
        self.assertTrue(uploads_confirmed(address, [Path('bank.pdf')]), address)
        self.assertFalse(uploads_confirmed(address, [Path('rk_deposit_a.png')]))
        self.assertTrue(uploads_confirmed(deposits, [Path('rk_deposit_a.png'), Path('rk_deposit_b.png')]), deposits)

    def state_for(self, path, html):
        self.page(html)
        analyzer = MexcPageStateAnalyzer()
        analyzer._ensure_relevant_mexc_tab = Mock(return_value={})
        def execute(script, *args):
            # Keep real browser DOM/layout while providing the fixture's MEXC URL.
            script = script.replace('window.location.href', repr('https://www.mexc.com' + path))
            script = script.replace('window.location.pathname', repr(path))
            return self.driver.execute_script(script, *args)
        with patch('automation.scenarios.mexc_state.detect_captcha', return_value=False):
            return analyzer.analyze(SimpleNamespace(execute_script=execute)).name

    def test_help_text_is_not_submission_success(self):
        state = self.state_for('/support/apply-risk-account-protection/form',
            '<h1>Risk Review Documents</h1><p>Once submitted, your application is under review.</p><input id="emailCode">')
        self.assertEqual(state, 'risk_control_form')

    def test_application_specific_confirmation(self):
        self.assertEqual(self.state_for('/support/apply-risk-account-protection/form',
            '<h1>Your application has been submitted.</h1>'), 'risk_control_submitted')

    def test_application_receipt_modal_can_overlay_form(self):
        self.assertEqual(self.state_for('/support/apply-risk-account-protection/form',
            '<input id="emailCode"><div role="dialog"><h2>Your application has been submitted.</h2></div>'),
            'risk_control_submitted')

    def test_generic_upload_success_is_not_application_receipt(self):
        self.assertEqual(self.state_for('/support/apply-risk-account-protection/form',
            '<h1>Risk Review Documents</h1><input id="emailCode"><div role="dialog"><h2>Submitted successfully</h2></div>'),
            'risk_control_form')

    def test_confirmed_intro_redirect(self):
        self.assertEqual(self.state_for('/support/apply-risk-account-protection/',
            '<h1>Account Risk Review</h1>'), 'risk_control_unavailable')

    def test_loading_intro_is_not_unavailable(self):
        self.assertNotEqual(self.state_for('/support/apply-risk-account-protection/',
            '<h1>Account Risk Review</h1><div aria-busy="true">Loading</div>'), 'risk_control_unavailable')

    def test_intro_without_slash_in_inactive_spin_container(self):
        self.assertEqual(self.state_for('/support/apply-risk-account-protection',
            '<div class="ant-spin-container"><h1>Account Risk Review</h1>'
            '<p>Please submit risk review documents</p><button>Apply</button>'
            '<button>Deposit</button></div>'), 'risk_control_unavailable')


if __name__ == '__main__':
    unittest.main()
