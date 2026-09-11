"""Section-scoped document upload and text entry for RK forms."""
import logging
import time
from pathlib import Path
from selenium.webdriver.remote.webelement import WebElement
from automation.scenarios.mexc_browser_helpers import clear_and_type
from services.rk_submission_files import upload_file_error

logger = logging.getLogger(__name__)


class RKDocumentsMixin:
    def _upload_optional_files(self, needles: tuple[str, ...], paths: list[Path], step_prefix: str) -> None:
        existing_paths = [path for path in paths if path and path.is_file() and path.stat().st_size > 0]
        if len(existing_paths) != len(paths):
            raise RuntimeError(f"A selected document is missing or empty in {needles[0]}. Choose files again.")
        if not existing_paths:
            self.debug.warning(f"{step_prefix}_files_missing")
            return
        for path in existing_paths:
            if error := upload_file_error(path):
                raise RuntimeError(error)
        snapshot = self._section_file_snapshot(needles)
        deadline = time.monotonic() + 60
        while snapshot.get('pending'):
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            if time.monotonic() >= deadline:
                raise RuntimeError(f'Existing upload is still pending in {needles[0]}.')
            time.sleep(0.5)
            snapshot = self._section_file_snapshot(needles)
        expected_names = {path.name.lower() for path in existing_paths}
        present_names = {str(name).lower() for name in snapshot.get('fileNamesExact', [])}
        if present_names - expected_names:
            raise RuntimeError(f'Different documents are already present in {needles[0]}. Review them before continuing.')
        present = [path for path in existing_paths if path.name.lower() in present_names]
        if snapshot.get('uploadError'):
            raise RuntimeError(f'MEXC rejected an upload in {needles[0]}. Remove the failed file before retrying.')
        if present and not uploads_confirmed(snapshot, present):
            if not self._wait_for_section_uploads(needles, present, timeout=60):
                raise RuntimeError(f'Existing upload is still unconfirmed in {needles[0]}.')
        remaining = [path for path in existing_paths if path.name.lower() not in present_names]
        if not remaining:
            self.debug.step(f'{step_prefix}_upload_reused', count=len(present))
            return
        input_element = self._wait_for_file_input_for_section(needles, timeout=12)
        if input_element is None:
            self.debug.save_page_probe(self.driver, f"{step_prefix}_file_input_not_found.json")
            raise RuntimeError(f"Upload field was not found for {needles[0]}")

        self.debug.step(f"{step_prefix}_upload_start", count=len(existing_paths))
        try:
            if len(remaining) > 1 and not input_element.get_attribute("multiple"):
                for path in remaining:
                    current = self._wait_for_file_input_for_section(needles, timeout=12)
                    if current is None:
                        raise RuntimeError("Upload input disappeared")
                    self._send_files(current, [path])
                    if not self._wait_for_section_uploads(needles, [path], timeout=60):
                        raise RuntimeError(f"Upload was not confirmed: {path.name}")
            else:
                self._send_files(input_element, remaining)
        except Exception as exc:
            logger.debug("File upload failed for %s", step_prefix, exc_info=True)
            self.debug.warning(f"{step_prefix}_upload_failed", error=str(exc))
            raise RuntimeError(f"Could not upload files for {needles[0]}: {exc}") from exc
        if not self._wait_for_section_uploads(needles, existing_paths, timeout=60):
            snapshot = self._section_file_snapshot(needles)
            self.debug.warning(f"{step_prefix}_upload_not_confirmed", snapshot=snapshot)
            self.debug.save_page_probe(self.driver, f"{step_prefix}_upload_not_confirmed.json")
            raise RuntimeError(f"Could not confirm uploaded files in the {needles[0]} section.")
        self.debug.step(f"{step_prefix}_upload_done", count=len(existing_paths))

    def _send_files(self, input_element: WebElement, paths: list[Path]) -> None:
        self.driver.execute_script(
            """
            const input = arguments[0];
            input.removeAttribute('hidden');
            input.style.display = 'block';
            input.style.visibility = 'visible';
            input.style.opacity = '1';
            input.style.width = '1px';
            input.style.height = '1px';
            """,
            input_element,
        )
        input_element.send_keys("\n".join(str(path.resolve()) for path in paths))

    def _wait_for_section_uploads(self, needles: tuple[str, ...], paths: list[Path], *, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            snapshot = self._section_file_snapshot(needles)
            if snapshot.get("uploadError"):
                raise RuntimeError(f"MEXC rejected an upload in {needles[0]}.")
            if uploads_confirmed(snapshot, paths):
                return True
            time.sleep(0.75)
        return False

    def _section_file_snapshot(self, needles: tuple[str, ...]) -> dict:
        try:
            data = self.driver.execute_script(
                """
                const needles = arguments[0].map((value) => String(value).toLowerCase());
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const normalizeLower = (value) => normalize(value).toLowerCase();
                const label = [...document.querySelectorAll('label')].find(e => visible(e)
                    && needles.some(n => (e.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase().startsWith(n)));
                const section = label?.closest('[class*="submitItem"], [class*="fileWrapper"]');
                const target = section ? {startY: section.getBoundingClientRect().top,
                    endY: section.getBoundingClientRect().bottom} : sectionBounds(needles);
                if (!target) return { found: false, text: '', fileNames: [] };
                const elements = [...(section || document).querySelectorAll('a,span,div,p,li')]
                    .filter(visible)
                    .filter((element) => {
                        const rect = element.getBoundingClientRect();
                        return !!section || rect.y >= target.startY - 2
                            && rect.y < target.endY - 2
                            && rect.y + rect.height <= target.endY + 8;
                    });
                const uploadItems = elements.filter(element => element.matches('li[class*="fileList"], .ant-upload-list-item'));
                const fileNamesExact = uploadItems.flatMap(element => [...element.querySelectorAll('span,a,[title]')]
                    .map(e => normalize(e.getAttribute('title') || e.innerText))
                    .filter(value => /\\.(pdf|png|jpe?g)$/i.test(value)));
                const uploadError = elements.some(e => e.matches('.ant-upload-list-item-error,[role="alert"]')
                    && /error|failed|invalid|exceed|unsupported/i.test(e.innerText || e.className));
                const pending = elements.some(e => e.matches('.ant-upload-list-item-uploading,[role="progressbar"],.ant-spin-spinning,[aria-busy="true"]'));
                const confirmed = uploadItems.length > 0 && uploadItems.every(e =>
                    e.classList.contains('ant-upload-list-item-done') || e.closest('.ant-form-item-has-success'));
                const text = normalize(elements.map((element) => element.innerText || element.textContent).join(' '));
                const fileNames = [...new Set((text.match(/[\\w .()\\-]+\\.(?:pdf|png|jpe?g)/gi) || []).map((value) => normalize(value)))];
                return {
                    found: true, fileNamesExact, uploadError, pending, confirmed,
                    startY: Math.round(target.startY),
                    endY: Math.round(target.endY),
                    text: text.slice(0, 1200),
                    fileNames: fileNames.slice(0, 20)
                };

                function sectionBounds(sectionNeedles) {
                    const knownTitles = [
                        'proof of address',
                        'occupation details',
                        'proof of source of last 1-2 deposits',
                        'email verification code'
                    ];
                    const titles = [...document.querySelectorAll('label,span,p,div,h1,h2,h3,h4')]
                        .filter(visible)
                        .map((element) => ({
                            text: normalizeLower(element.innerText || element.textContent),
                            rect: element.getBoundingClientRect()
                        }))
                        .filter((item) => item.text);
                    const targetTitles = titles
                        .filter((item) => sectionNeedles.some((needle) => item.text === needle || item.text.startsWith(needle)))
                        .sort((left, right) => (left.rect.height * left.rect.width) - (right.rect.height * right.rect.width));
                    const targetTitle = targetTitles[0];
                    if (!targetTitle) return null;
                    const titleYs = knownTitles.flatMap((title) =>
                        titles
                            .filter((item) => item.text === title || item.text.startsWith(title))
                            .map((item) => item.rect.y)
                    );
                    const submitY = [...document.querySelectorAll('button,[role="button"]')]
                        .filter(visible)
                        .filter((element) => normalizeLower(element.innerText || element.textContent).includes('submit application'))
                        .map((element) => element.getBoundingClientRect().y);
                    const after = [...titleYs, ...submitY, document.body.scrollHeight]
                        .filter((y) => y > targetTitle.rect.y + 8)
                        .sort((a, b) => a - b);
                    return { startY: targetTitle.rect.y, endY: after[0] || document.body.scrollHeight };
                }
                """,
                list(needles),
            )
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _wait_for_file_input_for_section(self, needles: tuple[str, ...], *, timeout: int) -> WebElement | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            element = self._find_file_input_for_section(needles)
            if element is not None:
                return element
            time.sleep(0.5)
        return None

    def _find_file_input_for_section(self, needles: tuple[str, ...]) -> WebElement | None:
        return self.driver.execute_script(
            """
            const needles = arguments[0].map((value) => String(value).toLowerCase());
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const label = [...document.querySelectorAll('label')].find(e => visible(e)
                    && needles.some(n => (e.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase().startsWith(n)));
                const section = label?.closest('[class*="submitItem"], [class*="fileWrapper"]');
                const target = section ? {startY: section.getBoundingClientRect().top,
                    endY: section.getBoundingClientRect().bottom} : sectionBounds(needles);
            if (!target) return null;
            if (section) return section.querySelector('input[type="file"]');
            const candidates = [...document.querySelectorAll('input[type="file"]')]
                .map((input) => ({ input, y: uploadY(input) }))
                .filter((item) => item.y >= target.startY - 2 && item.y < target.endY - 2)
                .sort((left, right) => left.y - right.y);
            return candidates[0]?.input || null;

            function sectionBounds(sectionNeedles) {
                const knownTitles = [
                    'proof of address',
                    'occupation details',
                    'proof of source of last 1-2 deposits',
                    'email verification code'
                ];
                const titles = [...document.querySelectorAll('label,span,p,div,h1,h2,h3,h4')]
                    .filter(visible)
                    .map((element) => ({
                        element,
                        text: normalize(element.innerText || element.textContent),
                        rect: element.getBoundingClientRect()
                    }))
                    .filter((item) => item.text);
                const targetTitles = titles
                    .filter((item) => sectionNeedles.some((needle) => item.text === needle || item.text.startsWith(needle)))
                    .sort((left, right) => (left.rect.height * left.rect.width) - (right.rect.height * right.rect.width));
                const targetTitle = targetTitles[0];
                if (!targetTitle) return null;
                const titleYs = knownTitles.flatMap((title) =>
                    titles
                        .filter((item) => item.text === title || item.text.startsWith(title))
                        .map((item) => item.rect.y)
                );
                const submitY = [...document.querySelectorAll('button,[role="button"]')]
                    .filter(visible)
                    .filter((element) => normalize(element.innerText || element.textContent).includes('submit application'))
                    .map((element) => element.getBoundingClientRect().y);
                const after = [...titleYs, ...submitY, document.body.scrollHeight]
                    .filter((y) => y > targetTitle.rect.y + 8)
                    .sort((a, b) => a - b);
                return { startY: targetTitle.rect.y, endY: after[0] || document.body.scrollHeight };
            }

            function uploadY(input) {
                let node = input;
                for (let i = 0; node && i < 10; i += 1, node = node.parentElement) {
                    const visibleUploads = [...node.querySelectorAll('.ant-upload, [class*="upload"], [class*="Upload"], button,[role="button"],span,div')]
                        .filter(visible)
                        .filter((element) => {
                            const text = normalize(element.innerText || element.textContent);
                            const classText = String(element.className || '').toLowerCase();
                            return text.includes('upload') || classText.includes('upload');
                        })
                        .map((element) => element.getBoundingClientRect().y)
                        .filter((y) => y > 0);
                    if (visibleUploads.length) {
                        return Math.min(...visibleUploads);
                    }
                }
                const rect = input.getBoundingClientRect();
                return rect.y;
            }
            """,
            list(needles),
        )

    def _fill_section_text(self, needles: tuple[str, ...], text: str, step_prefix: str) -> None:
        if not text:
            self.debug.warning(f"{step_prefix}_missing")
            return
        element = self._wait_for_text_input_for_section(needles, timeout=8)
        if element is None:
            self.debug.save_page_probe(self.driver, f"{step_prefix}_input_not_found.json")
            raise RuntimeError(f"Text field was not found for {needles[0]}")
        clear_and_type(self.driver, element, text)
        if not self._wait_for_element_value(element, text, timeout=6):
            self.debug.save_page_probe(self.driver, f"{step_prefix}_value_not_confirmed.json")
            raise RuntimeError(f"Could not confirm text in the {needles[0]} section.")
        self.debug.step(f"{step_prefix}_filled", length=len(text))

    def _wait_for_element_value(self, element: WebElement, expected: str, *, timeout: int) -> bool:
        expected_value = (expected or "").strip()
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            try:
                value = str(
                    self.driver.execute_script(
                        """
                        const element = arguments[0];
                        return element?.value || element?.innerText || element?.textContent || '';
                        """,
                        element,
                    )
                    or ""
                ).strip()
            except Exception:
                value = ""
            if value == expected_value or (expected_value and expected_value in value):
                return True
            time.sleep(0.35)
        return False

    def _wait_for_text_input_for_section(self, needles: tuple[str, ...], *, timeout: int) -> WebElement | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_cancelled()
            self._raise_if_browser_closed()
            element = self._find_text_input_for_section(needles)
            if element is not None:
                return element
            time.sleep(0.5)
        return None

    def _find_text_input_for_section(self, needles: tuple[str, ...]) -> WebElement | None:
        return self.driver.execute_script(
            """
            const needles = arguments[0].map((value) => String(value).toLowerCase());
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && !element.disabled;
            };
            const normalize = (value) => (value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const label = [...document.querySelectorAll('label')].find(e => visible(e)
                    && needles.some(n => (e.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase().startsWith(n)));
                const section = label?.closest('[class*="submitItem"], [class*="fileWrapper"]');
                const target = section ? {startY: section.getBoundingClientRect().top,
                    endY: section.getBoundingClientRect().bottom} : sectionBounds(needles);
            if (!target) return null;
            const inputs = [...(section || document).querySelectorAll('textarea,input')]
                .filter(visible)
                .filter((input) => {
                    const rect = input.getBoundingClientRect();
                    const type = normalize(input.type || '');
                    const attrs = normalize([
                        input.id,
                        input.name,
                        input.placeholder,
                        input.getAttribute('aria-label'),
                    ].join(' '));
                    if (!section && (rect.y < target.startY - 2 || rect.y >= target.endY - 2)) return false;
                    if (type === 'file' || type === 'checkbox' || type === 'radio' || type === 'hidden' || type === 'search') return false;
                    if (attrs.includes('email') && attrs.includes('code')) return false;
                    return true;
                })
                .sort((left, right) => left.getBoundingClientRect().y - right.getBoundingClientRect().y);
            return inputs[inputs.length - 1] || null;

            function sectionBounds(sectionNeedles) {
                const knownTitles = [
                    'proof of address',
                    'occupation details',
                    'proof of source of last 1-2 deposits',
                    'email verification code'
                ];
                const titles = [...document.querySelectorAll('label,span,p,div,h1,h2,h3,h4')]
                    .filter(visible)
                    .map((element) => ({
                        element,
                        text: normalize(element.innerText || element.textContent),
                        rect: element.getBoundingClientRect()
                    }))
                    .filter((item) => item.text);
                const targetTitles = titles
                    .filter((item) => sectionNeedles.some((needle) => item.text === needle || item.text.startsWith(needle)))
                    .sort((left, right) => (left.rect.height * left.rect.width) - (right.rect.height * right.rect.width));
                const targetTitle = targetTitles[0];
                if (!targetTitle) return null;
                const titleYs = knownTitles.flatMap((title) =>
                    titles
                        .filter((item) => item.text === title || item.text.startsWith(title))
                        .map((item) => item.rect.y)
                );
                const submitY = [...document.querySelectorAll('button,[role="button"]')]
                    .filter(visible)
                    .filter((element) => normalize(element.innerText || element.textContent).includes('submit application'))
                    .map((element) => element.getBoundingClientRect().y);
                const after = [...titleYs, ...submitY, document.body.scrollHeight]
                    .filter((y) => y > targetTitle.rect.y + 8)
                    .sort((a, b) => a - b);
                return { startY: targetTitle.rect.y, endY: after[0] || document.body.scrollHeight };
            }
            """,
            list(needles),
        )



def uploads_confirmed(snapshot: dict, paths: list[Path]) -> bool:
    """Require every full filename; common prefixes cannot identify two deposits."""
    if not snapshot.get('confirmed') or snapshot.get('pending') or snapshot.get('uploadError'):
        return False
    names = {str(name).lower() for name in snapshot.get('fileNamesExact', [])}
    return bool(paths) and all(path.name.lower() in names for path in paths)
