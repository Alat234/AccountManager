"""Bounded recovery of idempotent RK steps before any submission is attempted."""
from automation.recovery import PageState


class RKRecoveryMixin:
    def _run_recoverable_step(self, name, action):
        for attempt in range(2):
            try:
                return action()
            except Exception:
                self._rk_check_cancelled()
                if self._submission_attempted or attempt:
                    raise
                state = self.state_analyzer.analyze(self.driver)
                if self.driver.execute_script('return navigator.onLine') is False:
                    state = PageState('network_error', 1.0)
                if state.name not in {'network_error', 'network_loading', 'login'}:
                    raise
                self.debug.warning('rk_recovery_start', checkpoint=name, state=state.name)
                if state.name == 'login':
                    self._ensure_logged_in()
                elif self.network_recovery_handler:
                    decision = self.network_recovery_handler(name, state)
                    if decision == 'cancel':
                        raise RuntimeError('Scenario cancelled by user')
                    if decision == 'refresh':
                        self._open_rk_form()
                    elif decision != 'wait':
                        raise RuntimeError('RK recovery was not confirmed')
                else:
                    raise
                self._wait_for_rk_form()
                self._verify_review_checks()

    def _remember_form_document(self):
        self._form_document_id = self.driver.execute_script('return performance.timeOrigin')

    def _restore_if_document_reloaded(self):
        current = self.driver.execute_script('return performance.timeOrigin')
        if self._form_document_id is not None and current != self._form_document_id:
            self.debug.warning('rk_recovery_start', reason='form_reloaded')
            self._verify_review_checks()
            self._request_email_code()
            self._fill_documents()
            return True
        return False
