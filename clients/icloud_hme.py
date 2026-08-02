from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from clients.adspower import AdsPowerClient
from clients.adspower_selenium import open_adspower_selenium_driver

logger = logging.getLogger(__name__)

Locator = tuple[str, str]


@dataclass(frozen=True)
class ICloudHMESelectors:
    create_buttons: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, "button[title='Add']"),
        (By.CSS_SELECTOR, "button.button-icon-only[title='Add']"),
        (By.XPATH, "//button[@title='Add']"),
        (By.XPATH, "//button[contains(@class, 'button-icon-only')]"),
    )
    email_fields: tuple[Locator, ...] = (
        (By.XPATH, "//*[contains(@value, '@icloud.com')]"),
        (By.XPATH, "//*[contains(text(), '@icloud.com')]"),
        (By.CSS_SELECTOR, "input[type='email']"),
    )
    label_fields: tuple[Locator, ...] = (
        (By.XPATH, "//input[@placeholder='Label' or @aria-label='Label']"),
        (By.XPATH, "//textarea[@placeholder='Label' or @aria-label='Label']"),
        (By.XPATH, "//label[contains(., 'Label')]/following::input[1]"),
        (By.XPATH, "//label[contains(., 'Label')]/following::textarea[1]"),
        (By.CSS_SELECTOR, "input[name*='label' i]"),
        (By.CSS_SELECTOR, "textarea[name*='label' i]"),
    )
    submit_buttons: tuple[Locator, ...] = (
        (By.XPATH, "//button[contains(., 'Create email address')]"),
        (By.XPATH, "//button[contains(., 'Створити')]"),
        (By.CSS_SELECTOR, "aside#app-modal .modal-button-bar button.button-rounded-rectangle"),
        (By.CSS_SELECTOR, ".modal-button-bar button.button-rounded-rectangle"),
    )
    confirm_buttons: tuple[Locator, ...] = (
        (By.XPATH, "//button[contains(., 'Done')]"),
        (By.XPATH, "//button[contains(., 'Готово')]"),
        (By.XPATH, "//button[contains(., 'OK')]"),
    )


class ICloudHMEClient:
    ICLOUD_HME_URL = "https://www.icloud.com/icloudplus/hidemyemail"
    EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@icloud\.com", re.IGNORECASE)

    def __init__(
        self,
        adspower: AdsPowerClient,
        profile_id: str,
        *,
        selectors: ICloudHMESelectors | None = None,
        timeout: int = 30,
    ):
        self.adspower = adspower
        self.profile_id = profile_id
        self.selectors = selectors or ICloudHMESelectors()
        self.timeout = timeout
        self.driver: webdriver.Chrome | None = None
        self.progress_callback: Callable[[str, dict], None] | None = None

    def set_progress_callback(self, callback: Callable[[str, dict], None] | None) -> None:
        self.progress_callback = callback

    def create_mask(self, label: str | None = None) -> str:
        logger.info("Starting iCloud HME profile %s", self.profile_id)
        self._step("start")
        self.driver = self._open_driver()
        try:
            logger.info("Opening iCloud HME page")
            self._prepare_single_working_tab()
            self._step("open_icloud")
            self.driver.get(self.ICLOUD_HME_URL)
            self._wait_for_page()
            self._step("icloud_loaded")
            known_emails = self._collect_visible_emails()
            logger.info("Found %d existing HME addresses", len(known_emails))
            self._step("existing_addresses_detected", count=len(known_emails))

            logger.info("Clicking create HME address")
            self._step("create_address_open")
            self._click_create_button()
            time.sleep(2)

            logger.info("Reading generated HME address")
            self._step("generated_address_wait")
            email = self._wait_for_generated_email(exclude=known_emails)
            logger.info("Generated HME address: %s", email)
            self._step("generated_address_ready", email=email)

            label_text = label or self._default_label()
            logger.info("Filling iCloud HME label: %s", label_text)
            self._step("label_fill")
            self._fill_label(label_text)

            logger.info("Clicking 'Create email address' button")
            self._step("submit_create")
            self._click_submit_button()

            time.sleep(2)

            logger.info("Confirming created HME address")
            self._step("confirm_create")
            self._click_confirm_button()
            self._step("completed", email=email)
            return email
        except Exception:
            logger.exception("Failed to create iCloud HME mask")
            self._step("failed")
            raise
        finally:
            self._close_driver()

    def _step(self, step: str, **fields) -> None:
        if not self.progress_callback:
            return
        try:
            self.progress_callback(step, fields)
        except Exception:
            logger.debug("iCloud HME progress callback failed", exc_info=True)

    def _raise_if_browser_closed(self) -> None:
        driver = self.driver
        if driver is None:
            raise RuntimeError("iCloud AdsPower browser is closed")
        try:
            handles = list(driver.window_handles)
            if not handles:
                raise RuntimeError("iCloud AdsPower browser tab was closed")
            current = driver.current_window_handle
            if current not in handles:
                driver.switch_to.window(handles[0])
        except RuntimeError:
            raise
        except WebDriverException as exc:
            message = str(exc).lower()
            if any(fragment in message for fragment in (
                "no such window",
                "target window already closed",
                "web view not found",
                "invalid session",
                "disconnected",
            )):
                raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
            raise

    @staticmethod
    def _is_browser_closed_exception(exc: BaseException) -> bool:
        message = str(exc).lower()
        return any(fragment in message for fragment in (
            "no such window",
            "target window already closed",
            "web view not found",
            "invalid session",
            "disconnected",
        ))

    def _prepare_single_working_tab(self) -> None:
        self._raise_if_browser_closed()
        handles = list(self.driver.window_handles)
        if not handles:
            raise RuntimeError("iCloud AdsPower browser has no open tabs")
        keep = self._select_working_tab(handles)
        self.driver.switch_to.window(keep)
        closed = 0
        for handle in handles:
            if handle == keep:
                continue
            try:
                self.driver.switch_to.window(handle)
                self.driver.close()
                closed += 1
            except WebDriverException:
                logger.debug("Could not close extra iCloud AdsPower tab", exc_info=True)
        self.driver.switch_to.window(keep)
        if closed:
            logger.info("Closed %d extra iCloud AdsPower tabs before HME creation", closed)
            self._step("extra_tabs_closed", count=closed)

    def _select_working_tab(self, handles: list[str]) -> str:
        current = ""
        try:
            current = self.driver.current_window_handle
        except WebDriverException:
            current = ""

        fallback = current if current in handles else handles[0]
        for handle in handles:
            try:
                self.driver.switch_to.window(handle)
                url = (self.driver.current_url or "").lower()
                if "icloud.com" in url and ("hidemyemail" in url or "icloudplus" in url):
                    return handle
            except WebDriverException:
                logger.debug("Could not inspect AdsPower tab URL", exc_info=True)
        for handle in handles:
            try:
                self.driver.switch_to.window(handle)
                url = (self.driver.current_url or "").lower()
                if "icloud.com" in url:
                    return handle
            except WebDriverException:
                logger.debug("Could not inspect AdsPower tab URL", exc_info=True)
        return fallback

    def _open_driver(self) -> webdriver.Chrome:
        return open_adspower_selenium_driver(
            self.adspower,
            self.profile_id,
            context="ICloudHMEClient",
        )

    def _close_driver(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except WebDriverException:
                logger.debug("Selenium driver quit failed", exc_info=True)
            self.driver = None
        self.adspower.stop_browser(self.profile_id)
        logger.info("Stopped iCloud HME profile %s", self.profile_id)

    def _wait_for_page(self) -> None:
        WebDriverWait(self.driver, self.timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        self._wait_for_hme_content()

    def _wait_for_hme_content(self) -> None:
        def content_ready(driver):
            self._raise_if_browser_closed()
            text = driver.execute_script("return (document.body?.innerText || '')")
            if "@icloud.com" in text or "email address" in text.lower():
                return True
            frames = driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
            for frame in frames:
                try:
                    self._raise_if_browser_closed()
                    driver.switch_to.frame(frame)
                    text = driver.execute_script("return (document.body?.innerText || '')")
                    if "@icloud.com" in text or "email address" in text.lower():
                        return True
                except WebDriverException as exc:
                    if self._is_browser_closed_exception(exc):
                        raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
                    pass
                finally:
                    try:
                        driver.switch_to.default_content()
                    except WebDriverException:
                        pass
            return False

        logger.debug("Waiting for HME content to render")
        WebDriverWait(self.driver, self.timeout).until(content_ready)

    def _click_first(
        self,
        locators: tuple[Locator, ...],
        *,
        required: bool = True,
    ) -> bool:
        last_error: Exception | None = None
        for by, value in locators:
            try:
                self._raise_if_browser_closed()
                element = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((by, value))
                )
                element.click()
                return True
            except (TimeoutException, WebDriverException) as exc:
                if self._is_browser_closed_exception(exc):
                    raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
                last_error = exc
                logger.debug("Selector did not match: %s=%s", by, value)

        if required:
            raise RuntimeError("iCloud HME control was not found") from last_error
        return False

    def _switch_to_hme_frame(self) -> None:
        self.driver.switch_to.default_content()
        text = self.driver.execute_script("return (document.body?.innerText || '')")
        if "@icloud.com" in text:
            logger.debug("HME content in main frame")
            return
        frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        for i, frame in enumerate(frames):
            try:
                self._raise_if_browser_closed()
                self.driver.switch_to.frame(frame)
                text = self.driver.execute_script("return (document.body?.innerText || '')")
                if "@icloud.com" in text:
                    logger.debug("HME content found in iframe %d", i)
                    return
            except WebDriverException as exc:
                if self._is_browser_closed_exception(exc):
                    raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
                pass
            self.driver.switch_to.default_content()
        logger.debug("HME content not found in any iframe, staying in main frame")

    def _save_failure_screenshot(self) -> None:
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"logs/icloud_hme_failure_{ts}.png"
            self.driver.save_screenshot(path)
            logger.info("Saved failure screenshot: %s", path)
        except WebDriverException:
            logger.debug("Could not save failure screenshot", exc_info=True)

    def _click_create_button(self) -> None:
        if self._click_create_button_deep():
            return
        self._switch_to_hme_frame()
        if self._click_first(self.selectors.create_buttons, required=False):
            return
        self._dump_debug_context()
        self._save_failure_screenshot()
        raise RuntimeError("iCloud HME create button was not found")

    def _click_create_button_deep(self) -> bool:
        script = """
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            };
            const walk = (root, out) => {
                const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const node of nodes) {
                    out.push(node);
                    if (node.shadowRoot) walk(node.shadowRoot, out);
                }
            };
            const all = [];
            walk(document, all);

            // Find the "N active email addresses" heading (small element)
            let headingRect = null;
            for (const el of all) {
                if (!isVisible(el)) continue;
                const rect = el.getBoundingClientRect();
                if (rect.height > 80) continue;
                const text = (el.innerText || el.textContent || '').trim().toLowerCase();
                if (/\\d+\\s+active/.test(text) && (text.includes('email') || text.includes('адрес')))
                    { headingRect = rect; break; }
            }

            // Collect all visible Add buttons
            const addButtons = [];
            for (const el of all) {
                if (!isVisible(el)) continue;
                if (el.tagName.toLowerCase() !== 'button') continue;
                const title = (el.getAttribute('title') || '').toLowerCase();
                const cls = (el.getAttribute('class') || '').toLowerCase();
                if (title === 'add' || (cls.includes('button-icon-only') && el.querySelector('svg')))
                    addButtons.push(el);
            }
            if (!addButtons.length) return false;

            let target;
            if (headingRect && addButtons.length > 1) {
                // Pick the Add button closest (by Y) to the heading
                let bestDist = Infinity;
                for (const btn of addButtons) {
                    const dist = Math.abs(btn.getBoundingClientRect().top - headingRect.top);
                    if (dist < bestDist) { bestDist = dist; target = btn; }
                }
            } else {
                // Single button or no heading — pick by title preference
                target = addButtons.find(b => (b.getAttribute('title')||'').toLowerCase() === 'add')
                    || addButtons[0];
            }
            if (!target) return false;

            console.log('[HME-create] heading=' + (headingRect ? Math.round(headingRect.top) : 'none') +
                ' btn_top=' + Math.round(target.getBoundingClientRect().top) +
                ' buttons_found=' + addButtons.length);
            target.scrollIntoView({block: 'center', inline: 'center'});
            target.click();
            return true;
        """
        return self._run_script_in_frames(script)

    def _run_script_in_frames(self, script: str, *args) -> bool:
        self.driver.switch_to.default_content()
        try:
            return self._run_script_in_current_frame(script, *args, depth=0)
        finally:
            try:
                self.driver.switch_to.default_content()
            except WebDriverException:
                pass

    def _run_script_in_current_frame(self, script: str, *args, depth: int) -> bool:
        try:
            self._raise_if_browser_closed()
            if self.driver.execute_script(script, *args):
                return True
        except WebDriverException as exc:
            if self._is_browser_closed_exception(exc):
                raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
            logger.debug("Deep iCloud HME script failed in frame", exc_info=True)

        if depth >= 4:
            return False

        frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        for frame in frames:
            try:
                self._raise_if_browser_closed()
                self.driver.switch_to.frame(frame)
                if self._run_script_in_current_frame(script, *args, depth=depth + 1):
                    return True
            except WebDriverException as exc:
                if self._is_browser_closed_exception(exc):
                    raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
                logger.debug("Could not inspect iCloud frame", exc_info=True)
            finally:
                try:
                    self.driver.switch_to.parent_frame()
                except WebDriverException:
                    self.driver.switch_to.default_content()
        return False

    def _dump_debug_context(self) -> None:
        try:
            logger.debug("iCloud URL at failure: %s", self.driver.current_url)
            body = self.driver.find_element(By.TAG_NAME, "body").text
            logger.debug("iCloud body text at failure: %s", body[:2000])
        except WebDriverException:
            logger.debug("Could not dump iCloud debug context", exc_info=True)

    def _fill_first(self, locators: tuple[Locator, ...], text: str) -> bool:
        last_error: Exception | None = None
        for by, value in locators:
            try:
                self._raise_if_browser_closed()
                element = WebDriverWait(self.driver, 8).until(
                    EC.visibility_of_element_located((by, value))
                )
                element.clear()
                element.send_keys(text)
                return True
            except (TimeoutException, WebDriverException) as exc:
                if self._is_browser_closed_exception(exc):
                    raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
                last_error = exc
                logger.debug("Label selector did not match: %s=%s", by, value)
        raise RuntimeError("iCloud HME label field was not found") from last_error

    def _fill_label(self, text: str) -> None:
        if self._fill_label_deep(text):
            return
        self._switch_to_hme_frame()
        self._fill_first(self.selectors.label_fields, text)

    def _fill_label_deep(self, text: str) -> bool:
        script = """
            const value = arguments[0];
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            };
            const walk = (root, out) => {
                const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const node of nodes) {
                    out.push(node);
                    if (node.shadowRoot) walk(node.shadowRoot, out);
                }
            };
            const all = [];
            walk(document, all);
            const fields = all.map((el) => {
                const tag = el.tagName.toLowerCase();
                if ((tag !== 'input' && tag !== 'textarea') || !isVisible(el)) return false;
                const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                const name = (el.getAttribute('name') || '').toLowerCase();
                const id = (el.getAttribute('id') || '').toLowerCase();
                const parentText = (el.closest('form,section,div')?.innerText || '').toLowerCase();
                let score = 0;
                if (placeholder.includes('label')) score += 30;
                if (aria.includes('label')) score += 25;
                if (name.includes('label') || id.includes('label')) score += 20;
                if (parentText.includes('label')) score += 8;
                if (!score) return false;
                const rect = el.getBoundingClientRect();
                return {el, score, top: rect.top};
            }).filter(Boolean);
            fields.sort((a, b) => (b.score - a.score) || (a.top - b.top));
            const target = fields[0]?.el;
            if (!target) return false;
            target.focus();
            const proto = target.tagName.toLowerCase() === 'textarea'
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (setter) setter.call(target, value);
            else target.value = value;
            target.dispatchEvent(new Event('input', {bubbles: true}));
            target.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        """
        return self._run_script_in_frames(script, text)

    def _click_submit_button(self) -> None:
        time.sleep(1)
        if self._click_modal_submit_deep():
            logger.info("Submit clicked via modal-aware deep JS")
            return
        self._switch_to_hme_frame()
        if self._click_first(self.selectors.submit_buttons, required=False):
            logger.info("Submit clicked via Selenium selector")
            return
        if self._click_deep_button((
            "create email address", "create address",
            "створити адресу", "створити е-адресу", "створити",
        )):
            logger.info("Submit clicked via deep button fallback")
            return
        self._save_failure_screenshot()
        raise RuntimeError("iCloud HME submit button was not found")

    def _click_modal_submit_deep(self) -> bool:
        script = """
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            };
            const walk = (root, out) => {
                const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const node of nodes) {
                    out.push(node);
                    if (node.shadowRoot) walk(node.shadowRoot, out);
                }
            };
            const all = [];
            walk(document, all);

            // Find the modal container
            let modal = null;
            for (const el of all) {
                const id = (el.getAttribute('id') || '').toLowerCase();
                const cls = (el.getAttribute('class') || '').toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();
                if ((id === 'app-modal' || cls.includes('modal-dialog') || role === 'dialog') &&
                    isVisible(el)) {
                    modal = el;
                    break;
                }
            }
            if (!modal) {
                console.log('[HME-submit] no modal found');
                return false;
            }

            // Find buttons inside the modal
            const buttons = [];
            const walkModal = (root) => {
                for (const node of (root.querySelectorAll ? root.querySelectorAll('button, [role=button]') : [])) {
                    if (isVisible(node)) buttons.push(node);
                    if (node.shadowRoot) walkModal(node.shadowRoot);
                }
            };
            walkModal(modal);

            if (!buttons.length) {
                console.log('[HME-submit] no buttons in modal');
                return false;
            }

            // Try to match by text (EN + UK)
            const labels = ['create email address', 'create address',
                'створити адресу', 'створити е-адресу', 'створити е‑адресу',
                'створити'];
            for (const label of labels) {
                const btn = buttons.find(b => {
                    const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                    return t.includes(label) && !t.includes('cancel') && !t.includes('скасувати');
                });
                if (btn) {
                    console.log('[HME-submit] clicking by label: ' + label);
                    btn.scrollIntoView({block: 'center'});
                    btn.click();
                    return true;
                }
            }

            // Fallback: pick the last non-cancel button (primary action is usually last)
            const nonCancel = buttons.filter(b => {
                const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                return !t.includes('cancel') && !t.includes('скасувати') && t.length > 0;
            });
            if (nonCancel.length) {
                const btn = nonCancel[nonCancel.length - 1];
                console.log('[HME-submit] clicking last non-cancel: ' + btn.innerText);
                btn.scrollIntoView({block: 'center'});
                btn.click();
                return true;
            }

            console.log('[HME-submit] no suitable button in modal');
            return false;
        """
        return self._run_script_in_frames(script)

    def _click_confirm_button(self) -> None:
        if self._click_deep_button(("done", "готово", "save", "зберегти", "ok")):
            logger.info("Confirm clicked via deep button")
            return
        self._switch_to_hme_frame()
        if self._click_first(self.selectors.confirm_buttons, required=False):
            logger.info("Confirm clicked via Selenium selector")
            return
        logger.info("No confirm button found — dialog may auto-close")

    def _click_deep_button(self, labels: tuple[str, ...]) -> bool:
        script = """
            const labels = arguments[0];
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            };
            const walk = (root, out) => {
                const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const node of nodes) {
                    out.push(node);
                    if (node.shadowRoot) walk(node.shadowRoot, out);
                }
            };
            const all = [];
            walk(document, all);
            const candidates = all.map((el) => {
                if (!isVisible(el)) return false;
                const tag = el.tagName.toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();
                const clickable = tag === 'button' || role === 'button' ||
                    el.onclick || el.tabIndex >= 0 || el.closest('button,[role="button"]');
                if (!clickable) return false;
                const text = [
                    el.innerText || el.textContent || '',
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || ''
                ].join(' ').trim().toLowerCase();
                const matched = labels.find((label) => text.includes(label));
                if (!matched) return false;
                const target = el.closest('button,[role="button"]') || el;
                const rect = target.getBoundingClientRect();
                let score = matched.length;
                if (!target.disabled && target.getAttribute('aria-disabled') !== 'true') score += 20;
                if (rect.top > window.innerHeight * 0.25) score += 5;
                return {target, score, top: rect.top};
            }).filter(Boolean);
            candidates.sort((a, b) => (b.score - a.score) || (b.top - a.top));
            const target = candidates[0]?.target;
            if (!target) return false;
            target.scrollIntoView({block: 'center', inline: 'center'});
            target.click();
            return true;
        """
        return self._run_script_in_frames(script, list(labels))

    def _wait_for_generated_email(self, *, exclude: set[str] | None = None) -> str:
        exclude = {email.lower() for email in (exclude or set())}

        def find_email(_driver) -> str | bool:
            for email in self._collect_visible_emails():
                if email.lower() not in exclude:
                    return email
            return False

        return WebDriverWait(self.driver, self.timeout).until(find_email)

    def _collect_visible_emails(self) -> set[str]:
        emails: set[str] = set()
        for text in self._collect_visible_texts():
            for match in self.EMAIL_RE.finditer(text):
                emails.add(match.group(0))
        return emails

    def _collect_visible_texts(self) -> list[str]:
        script = """
            const isVisible = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            };
            const walk = (root, out) => {
                const nodes = root.querySelectorAll ? root.querySelectorAll('*') : [];
                for (const node of nodes) {
                    if (isVisible(node)) {
                        out.push(node.innerText || node.textContent || '');
                        out.push(node.getAttribute('value') || '');
                        out.push(node.getAttribute('aria-label') || '');
                    }
                    if (node.shadowRoot) walk(node.shadowRoot, out);
                }
            };
            const out = [];
            walk(document, out);
            return out.filter(Boolean).join('\\n');
        """
        texts: list[str] = []
        self.driver.switch_to.default_content()
        try:
            self._collect_visible_texts_current_frame(script, texts, depth=0)
        finally:
            self.driver.switch_to.default_content()
        return texts

    def _collect_visible_texts_current_frame(self, script: str, texts: list[str], *, depth: int) -> None:
        try:
            self._raise_if_browser_closed()
            text = self.driver.execute_script(script)
            if text:
                texts.append(str(text))
        except WebDriverException as exc:
            if self._is_browser_closed_exception(exc):
                raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
            logger.debug("Could not collect iCloud text in frame", exc_info=True)

        if depth >= 4:
            return

        frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe, frame")
        for frame in frames:
            try:
                self._raise_if_browser_closed()
                self.driver.switch_to.frame(frame)
                self._collect_visible_texts_current_frame(script, texts, depth=depth + 1)
            except WebDriverException as exc:
                if self._is_browser_closed_exception(exc):
                    raise RuntimeError("iCloud AdsPower browser tab was closed") from exc
                logger.debug("Could not inspect iCloud text frame", exc_info=True)
            finally:
                try:
                    self.driver.switch_to.parent_frame()
                except WebDriverException:
                    self.driver.switch_to.default_content()

    def _extract_email(self, element: WebElement) -> str:
        values = [
            element.get_attribute("value") or "",
            element.get_attribute("aria-label") or "",
            element.text or "",
        ]
        for value in values:
            match = self.EMAIL_RE.search(value)
            if match:
                return match.group(0)
        return ""

    @staticmethod
    def _default_label() -> str:
        return f"MEXC {datetime.now():%Y-%m-%d %H%M%S}"
