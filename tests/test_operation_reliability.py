import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import quote

from automation.operation_control import OperationControl, OperationCancelled
from automation.base import BaseScenario, ScenarioResult
from automation.scenarios.verified_input import fill_verified
from automation.scenarios.security_submit import click_code_submit
from services.task_service import TaskService
from models.task import AutomationTask


class ControlTests(unittest.TestCase):
    def test_atomic_submit_defers_pause_but_not_cancel(self):
        control = OperationControl()
        with control.atomic():
            control.pause()
            control.check()
            self.assertEqual(control.snapshot()['state'], 'pause_requested')
            control.cancel()
            with self.assertRaises(OperationCancelled): control.check()

    def test_blank_tab_navigates_without_wait_or_manual_assistance(self):
        from automation.checkpoints import CheckpointRunner, ScenarioCheckpoint
        from automation.recovery import PageState
        action = Mock()
        runner = CheckpointRunner(driver_getter=Mock(), analyzer=Mock(), debug=Mock())
        runner._analyze = Mock(side_effect=[PageState('unknown', .2, url='about:blank'),
                                           PageState('register_email', .82)])
        runner._wait_for_known_state = Mock(side_effect=AssertionError('Must navigate first'))
        runner._manual_assist = Mock(side_effect=AssertionError('No assistance for blank tab'))
        runner._emit_resource = Mock()
        runner.run([ScenarioCheckpoint('navigate', action, allowed_states={'unknown'},
                     done_states={'register_email'}, initial_navigation=True)])
        action.assert_called_once()

    def test_existing_form_skips_initial_navigation(self):
        from automation.checkpoints import CheckpointRunner, ScenarioCheckpoint
        from automation.recovery import PageState
        action = Mock()
        runner = CheckpointRunner(driver_getter=Mock(), analyzer=Mock(), debug=Mock())
        runner._analyze = Mock(return_value=PageState('api_form', .88))
        runner._emit_resource = Mock()
        runner.run([ScenarioCheckpoint('navigate', action, done_states={'api_form'}, initial_navigation=True)])
        action.assert_not_called()

    def test_pause_blocks_worker_until_resume(self):
        control = OperationControl()
        control.pause()
        done = threading.Event()
        thread = threading.Thread(target=lambda: (control.check(), done.set()))
        thread.start()
        self.assertFalse(done.wait(.05))
        self.assertEqual(control.snapshot()['state'], 'paused')
        control.resume()
        self.assertTrue(done.wait(1))
        thread.join(1)

    def test_cancel_releases_paused_worker(self):
        control = OperationControl()
        control.pause()
        errors = []
        def run():
            try: control.check()
            except OperationCancelled: errors.append('cancelled')
        thread = threading.Thread(target=run)
        thread.start()
        control.cancel()
        thread.join(1)
        self.assertEqual(errors, ['cancelled'])

    def test_cancel_never_calls_browser_on_ui_thread(self):
        class Scenario(BaseScenario):
            def run(self): return ScenarioResult(True, 'ok')
        scenario = Scenario(Mock(), SimpleNamespace(email='test', ads_profile_id='id'))
        scenario.driver = Mock()
        scenario.cancel()
        scenario.driver.quit.assert_not_called()
        scenario.adspower.stop_browser.assert_not_called()
        self.assertFalse(scenario.auto_close)
        result = scenario.execute()
        self.assertEqual(result.data['operation_status'], 'cancelled')

    def test_cancel_after_submit_is_unknown(self):
        class Scenario(BaseScenario):
            def _start_browser(self): pass
            def run(self):
                self._external_action_pending = True
                self.cancel()
                self._raise_if_cancelled()
        scenario = Scenario(Mock(), SimpleNamespace(email='test', ads_profile_id='id'))
        result = scenario.execute()
        self.assertEqual(result.data['operation_status'], 'outcome_unknown')

    def test_task_keeps_cancelled_status(self):
        db = Mock()
        service = TaskService(db)
        task = AutomationTask('task', 'account', 'scenario')
        db.mutate_task.side_effect = lambda task_id, change: (change(task), task)[1]
        service.complete_task('task', ScenarioResult(False, 'cancelled', {'operation_status': 'cancelled'}))
        self.assertEqual(task.status, 'cancelled')

    def test_worker_after_only_enqueues(self):
        from ui.thread_dispatch import ThreadDispatchMixin
        class TkStub:
            def after(self, *args): self.called.append(threading.get_ident())
        class App(ThreadDispatchMixin, TkStub):
            called = []
        app = App()
        app.init_dispatch()
        thread = threading.Thread(target=lambda: app.after(0, lambda: None))
        thread.start(); thread.join()
        self.assertEqual(app.called, [threading.get_ident()])
        self.assertFalse(app._ui_calls.empty())


@unittest.skipUnless(os.environ.get('RK_TEST_CHROMEDRIVER'), 'Requires isolated Chrome')
class InputBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        options = webdriver.ChromeOptions()
        options.binary_location = os.environ.get('RK_TEST_CHROME', '')
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        cls.driver = webdriver.Chrome(service=Service(os.environ['RK_TEST_CHROMEDRIVER']), options=options)

    @classmethod
    def tearDownClass(cls): cls.driver.quit()

    def page(self, html): self.driver.get('data:text/html;charset=utf-8,' + quote(html))

    def test_silent_keyboard_failure_uses_verified_fallback(self):
        self.page('<input id="memo">')
        real = self.driver.find_element('id', 'memo')
        fake = Mock()
        fake.get_attribute.return_value = ''
        calls = iter([fake, real, real, real, real, real])
        fill_verified(self.driver, real, 'trading', locate=lambda: next(calls, real))
        self.assertEqual(real.get_attribute('value'), 'trading')

    def test_input_that_resets_on_blur_is_rejected(self):
        self.page('<input id="memo" onblur="this.value=\'\'" onchange="this.value=\'\'">')
        with self.assertRaises(RuntimeError):
            fill_verified(self.driver, self.driver.find_element('id', 'memo'), 'trading')

    def test_textarea_fallback_uses_correct_prototype(self):
        self.page('<textarea id="memo" readonly></textarea>')
        element = self.driver.find_element('id', 'memo')
        fill_verified(self.driver, element, 'trading')
        self.assertEqual(element.get_attribute('value'), 'trading')

    def test_replaced_input_is_found_again(self):
        self.page('''<input id="memo"><script>memo.addEventListener('blur',()=>{
          const copy=memo.cloneNode();copy.value=memo.value;memo.replaceWith(copy);
        },{once:true});</script>''')
        fill_verified(self.driver, self.driver.find_element('id', 'memo'), 'trading')
        self.assertEqual(self.driver.find_element('id','memo').get_attribute('value'), 'trading')

    def test_submit_uses_input_form_and_ignores_unrelated_button(self):
        self.page('''<button onclick="window.wrong=true">Submit</button>
          <form onsubmit="event.preventDefault();window.correct=true"><input id="emailCode">
          <button>Submit</button></form>''')
        self.assertTrue(click_code_submit(self.driver, field_id='emailCode'))
        self.assertTrue(self.driver.execute_script('return window.correct===true && !window.wrong'))

    def test_disabled_submit_is_not_clicked(self):
        self.page('<form><input id="emailCode"><button disabled>Submit</button></form>')
        self.assertFalse(click_code_submit(self.driver, field_id='emailCode', timeout=.3))

    def test_background_submit_settles_modal_entrance(self):
        self.page('''<style>.ant-zoom-appear-prepare{opacity:0;transform:scale(0)}</style>
          <div role="dialog" class="ant-modal ant-zoom-appear ant-zoom-appear-prepare">
          <div class="ant-modal-content"><form><input id="emailCode"></form>
          <button onclick="window.submitted=(window.submitted||0)+1">Submit</button></div></div>''')
        self.driver.execute_script("Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true})")
        self.assertTrue(click_code_submit(self.driver, field_id='emailCode'))
        self.assertEqual(self.driver.execute_script('return window.submitted'), 1)

    def test_background_inline_submit(self):
        self.page('<form><input id="validationCode"><button type="button" onclick="window.submitted=true">Submit</button></form>')
        self.driver.execute_script("Object.defineProperty(document,'visibilityState',{value:'hidden',configurable:true})")
        self.assertTrue(click_code_submit(self.driver, field_id='validationCode'))
        self.assertTrue(self.driver.execute_script('return window.submitted'))

    def test_submit_delivers_native_pointer_sequence(self):
        self.page('''<form onsubmit="event.preventDefault()"><input id="validationCode">
          <button id="submitButton" type="submit">Submit</button></form>
          <script>window.events=[];
          for(const name of ['pointerdown','mousedown','mouseup','click'])
            submitButton.addEventListener(name,e=>window.events.push([e.type,e.isTrusted]));
          </script>''')
        self.assertTrue(click_code_submit(self.driver, field_id=('googleAuthCode','validationCode')))
        events = self.driver.execute_script('return window.events')
        self.assertEqual([item[0] for item in events], ['pointerdown','mousedown','mouseup','click'])
        self.assertTrue(all(item[1] for item in events))

    def test_inline_authenticator_validation_code_submit(self):
        self.page('''<input id="googleAuthCode" style="display:none">
          <button onclick="window.wrong=true">Submit</button>
          <form onsubmit="event.preventDefault();window.correct=true">
          <div><label for="validationCode">Authenticator Code</label><input id="validationCode"></div>
          <div><div><button type="submit">Submit</button></div></div></form>''')
        self.assertTrue(click_code_submit(self.driver, field_id=('googleAuthCode','validationCode')))
        self.assertTrue(self.driver.execute_script('return window.correct===true && !window.wrong'))

    def test_authenticator_selection_does_not_submit_email_form(self):
        self.page('''<form onsubmit="event.preventDefault();window.wrong=true">
          <input id="emailCode"><button>Submit</button></form>''')
        self.assertFalse(click_code_submit(self.driver, field_id=('googleAuthCode','validationCode'), timeout=.3))
        self.assertFalse(self.driver.execute_script('return !!window.wrong'))

    def test_modal_footer_submit_outside_inner_form(self):
        self.page('''<button onclick="window.wrong=true">Next</button>
          <div role="dialog"><div class="ant-modal-content"><div class="ant-modal-body">
          <div class="content"><form><div><input id="emailCode" value="123456"></div></form>
          <div class="footer"><button type="submit" onclick="window.correct=true">Submit</button></div>
          </div></div></div></div>''')
        self.assertTrue(click_code_submit(self.driver, field_id='emailCode'))
        self.assertTrue(self.driver.execute_script('return window.correct===true && !window.wrong'))

    def test_missing_modal_submit_does_not_click_page_button(self):
        self.page('''<button onclick="window.wrong=true">Submit</button>
          <div role="dialog"><form><input id="emailCode"></form></div>''')
        self.assertFalse(click_code_submit(self.driver, field_id='emailCode', timeout=.3))
        self.assertFalse(self.driver.execute_script('return !!window.wrong'))

    def test_no_captcha_does_not_sleep_eight_seconds(self):
        from automation.scenarios.mexc_browser_helpers import handle_mexc_captcha
        self.page('<p>Page ready</p>')
        ctx = SimpleNamespace(driver=self.driver, debug=Mock(), cancel_event=None, cancel_checker=None)
        started = time.monotonic()
        handle_mexc_captcha(ctx, 'test')
        self.assertLess(time.monotonic()-started, 2)


@unittest.skipUnless(os.name == 'nt', 'Windows Tk integration')
class OperationUITests(unittest.TestCase):
    def test_controls_survive_clearing_history(self):
        import customtkinter as ctk
        from ui.activity_log import ActivityLogPanel
        from ui.thread_dispatch import ThreadDispatchMixin
        class Root(ThreadDispatchMixin, ctk.CTk): pass
        root = Root()
        root.withdraw()
        root.init_dispatch()
        try:
            panel = ActivityLogPanel(root)
            panel.pack()
            control = OperationControl()
            scenario = SimpleNamespace(control=control, pause=control.pause, resume=control.resume, cancel=control.cancel)
            op = dict(scenario=scenario, title='API', step='Notes', step_at=time.monotonic())
            panel.set_operation(op)
            panel.active.pause_button.invoke()
            panel.set_operation(op)
            self.assertEqual(panel.active.pause_button.cget('text'), 'Продовжити')
            panel.clear()
            self.assertEqual(panel.active.winfo_manager(), 'grid')
            panel.active.pause_button.invoke()
            panel.active.stop_button.invoke()
            self.assertTrue(control.cancelled.is_set())
            panel.set_operation(None)
            self.assertEqual(panel.active.winfo_manager(), '')
        finally:
            root.destroy()


if __name__ == '__main__': unittest.main()
