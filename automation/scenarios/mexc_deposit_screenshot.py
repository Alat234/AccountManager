from __future__ import annotations

import json
from copy import deepcopy
import base64
import re
import time
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
from selenium.webdriver.support.ui import WebDriverWait

from automation.base import BaseScenario, ScenarioResult
from clients.adspower_selenium import open_adspower_selenium_driver


class MexcDepositScreenshotScenario(BaseScenario):
    RECORD_URL = "https://www.mexc.com/assets/record"
    VERSION = "2026-08-31-native-modal-foreground-assist"
    MAX_WITHDRAWAL_PAGES = 12
    MAX_CANDIDATES_PER_PAGE = 10
    FOREGROUND_ASSIST_TIMEOUT_SECONDS = 240

    def __init__(
        self,
        adspower,
        account,
        *,
        main_profile_id: str,
        account_dir: Path,
        captcha_service=None,
    ):
        super().__init__(adspower, account, captcha_service)
        self.main_profile_id = main_profile_id.strip()
        self.account_dir = Path(account_dir)
        self.auto_close = False
        self._record_window_handle: str | None = None

    def _start_browser(self) -> None:
        if not self.main_profile_id:
            raise RuntimeError("Set iCloud Profile ID in Settings first")
        self._log_step("mexc_deposit_screenshot_browser_start", profile_id=self.main_profile_id)
        self.driver = open_adspower_selenium_driver(
            self.adspower,
            self.main_profile_id,
            context=type(self).__name__,
        )

    @property
    def browser_profile_id(self):
        return self.main_profile_id

    def prepare(self):
        self._deposit_selection = deepcopy(self._load_selected_deposits())

    def run(self) -> ScenarioResult:
        deposits, deposit_path = (self._deposit_selection if hasattr(self, '_deposit_selection')
                                  else self._load_selected_deposits())
        if not deposits:
            raise RuntimeError("No selected RK deposits. Open RK Deposits and select at least one deposit.")

        deposits = [self._prepare_match_deposit(deposit) for deposit in deposits]
        saved_paths: list[str] = []
        failures: list[dict[str, Any]] = []
        self._log_step(
            "mexc_deposit_screenshot_start",
            deposit_path=str(deposit_path),
            selected_count=len(deposits),
            version=self.VERSION,
        )

        for index, deposit in enumerate(deposits, start=1):
            label = self._deposit_label(deposit)
            try:
                self._raise_if_running()
                self._open_withdrawal_history(force_reload=True)
                self._install_network_probe()
                self._try_click_withdrawal_tab()
                details_root = self._open_matching_withdrawal_details(deposit)

                screenshot_path = self._unique_screenshot_path(deposit, index)
                self._save_details_screenshot(details_root, screenshot_path)
                saved_paths.append(str(screenshot_path))
                self._log_step("mexc_deposit_screenshot_saved", path=str(screenshot_path), deposit=label)
            except Exception as exc:
                failures.append({"deposit": label, "error": str(exc)})
                self._log_step("mexc_deposit_screenshot_deposit_failed", deposit=label, error=str(exc))
            finally:
                self._close_details_modal()

        if not saved_paths:
            details = "; ".join(f"{item['deposit']}: {item['error']}" for item in failures[:3])
            raise RuntimeError(
                f"Could not save RK deposit screenshots. {details or 'No matching withdrawal details were found.'}"
            )

        message = f"Saved {len(saved_paths)}/{len(deposits)} RK deposit screenshot(s)."
        if failures:
            message += f" Failed: {len(failures)}."
        return ScenarioResult(
            success=True,
            message=message,
            data={
                "account_email": self.account.email,
                "screenshot_path": saved_paths[0],
                "screenshot_paths": saved_paths,
                "failures": failures,
                "deposit_path": str(deposit_path),
            },
        )

    def _load_selected_deposits(self) -> tuple[list[dict[str, Any]], Path]:
        deposits_path = self.account_dir / "rk_deposits.json"
        if deposits_path.exists():
            payload = json.loads(deposits_path.read_text(encoding="utf-8"))
            items = payload.get("deposits") if isinstance(payload, dict) else payload
            if not isinstance(items, list):
                raise RuntimeError("rk_deposits.json has an invalid format.")
            selected = [
                dict(item)
                for item in items
                if isinstance(item, dict) and bool(item.get("selected"))
            ]
            return selected, deposits_path

        deposit_path = self.account_dir / "rk_deposit.json"
        if deposit_path.exists():
            return [json.loads(deposit_path.read_text(encoding="utf-8"))], deposit_path

        raise RuntimeError("RK deposit data was not found. Open RK Deposits first.")

    def _prepare_match_deposit(self, deposit: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(deposit)
        coin = str(prepared.get("coin") or "")
        prepared["coin_base"] = coin.split("-", 1)[0] if "-" in coin else coin
        insert_time = int(prepared.get("insert_time") or 0)
        if insert_time:
            local_dt = datetime.fromtimestamp(insert_time / 1000)
            utc_dt = datetime.fromtimestamp(insert_time / 1000, tz=timezone.utc)
            prepared["date_hints"] = [
                local_dt.strftime("%Y-%m-%d"),
                local_dt.strftime("%Y/%m/%d"),
                local_dt.strftime("%m-%d"),
                local_dt.strftime("%H:%M"),
                utc_dt.strftime("%Y-%m-%d"),
                utc_dt.strftime("%H:%M"),
            ]
        else:
            prepared["date_hints"] = []
        prepared["address_hints"] = self._compact_identifier_hints(str(prepared.get("address") or ""))
        prepared["tx_hints"] = self._compact_identifier_hints(
            str(prepared.get("tx_id") or prepared.get("txId") or "")
        )
        return prepared

    def _compact_identifier_hints(self, value: str) -> list[str]:
        normalized = re.sub(r"\s+", "", str(value or "")).lower()
        if len(normalized) < 10:
            return []

        hints: set[str] = set()
        for prefix_len in range(5, min(len(normalized) - 3, 11)):
            for suffix_len in range(4, min(len(normalized) - prefix_len, 9)):
                prefix = normalized[:prefix_len]
                suffix = normalized[-suffix_len:]
                hints.add(f"{prefix}...{suffix}")
                hints.add(f"{prefix}…{suffix}")
        return sorted(hints)

    def _unique_screenshot_path(self, deposit: dict[str, Any], index: int) -> Path:
        base_path = self.account_dir / self._screenshot_filename(deposit, index)
        if not base_path.exists():
            return base_path
        stem = base_path.stem
        suffix = base_path.suffix
        counter = 2
        while True:
            candidate = base_path.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _screenshot_filename(self, deposit: dict[str, Any], index: int) -> str:
        insert_time = int(deposit.get("insert_time") or 0)
        if insert_time:
            time_part = datetime.fromtimestamp(insert_time / 1000).strftime("%Y-%m-%d_%H%M%S")
        else:
            time_part = f"unknown_{index}"
        amount = self._safe_filename_part(str(deposit.get("amount") or "amount"))
        coin = self._safe_filename_part(str(deposit.get("coin_base") or deposit.get("coin") or "coin"))
        return f"rk_deposit_{time_part}_{amount}_{coin}.png"

    @staticmethod
    def _safe_filename_part(value: str) -> str:
        clean = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value.strip())
        clean = clean.strip("._-")
        return clean or "value"

    def _deposit_label(self, deposit: dict[str, Any]) -> str:
        time_text = "-"
        insert_time = int(deposit.get("insert_time") or 0)
        if insert_time:
            time_text = datetime.fromtimestamp(insert_time / 1000).strftime("%Y-%m-%d %H:%M:%S")
        return f"{time_text} {deposit.get('amount') or '-'} {deposit.get('coin') or ''}".strip()

    def _open_withdrawal_history(self, *, force_reload: bool = False) -> None:
        self._log_step("mexc_deposit_screenshot_open_history", url=self.RECORD_URL, force_reload=force_reload)
        self._raise_if_running()
        self._ensure_record_tab()
        current_url = (self.driver.current_url or "").lower()
        if force_reload or "mexc.com" not in current_url or "/assets/record" not in current_url:
            self.driver.get(self.RECORD_URL)
            self._record_window_handle = self.driver.current_window_handle
        WebDriverWait(self.driver, 45).until(
            lambda driver: driver.execute_script("return document.readyState") in ("interactive", "complete")
        )
        self.control.wait(4)
        self._raise_if_running()
        current_url = (self.driver.current_url or "").lower()
        if "login" in current_url or "sign-in" in current_url or "signin" in current_url:
            raise RuntimeError("Main MEXC profile is not logged in. Log in in the iCloud AdsPower profile first.")

    def _try_click_withdrawal_tab(self) -> None:
        self._raise_if_running()
        self._ensure_record_tab()
        clicked = self.driver.execute_script(
            """
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none';
            };
            const candidates = [...document.querySelectorAll('button,a,[role="tab"],[role="button"],span,div')]
                .filter(visible)
                .filter((element) => /withdraw|withdrawal/i.test(element.innerText || element.textContent || ''))
                .sort((left, right) => {
                    const lr = left.getBoundingClientRect();
                    const rr = right.getBoundingClientRect();
                    return (lr.width * lr.height) - (rr.width * rr.height);
                });
            for (const element of candidates) {
                const target = element.closest('button,a,[role="tab"],[role="button"]') || element;
                target.scrollIntoView({ block: 'center', inline: 'center' });
                target.click();
                return true;
            }
            return false;
            """
        )
        self._log_step("mexc_deposit_screenshot_withdraw_tab", clicked=bool(clicked))
        if clicked:
            self.control.wait(3)
            self._raise_if_running()

    def _install_network_probe(self) -> None:
        self._raise_if_running()
        self._ensure_record_tab()
        installed = self.driver.execute_script(
            """
            if (window.__mexcAutomationNetworkProbeInstalled) return true;
            window.__mexcAutomationNetworkProbeInstalled = true;
            window.__mexcAutomationNetworkProbe = [];
            const shouldKeep = (url) => /mexc|asset|withdraw|record|history|transaction|capital|wallet/i.test(String(url || ''));
            const pushEntry = (entry) => {
                try {
                    if (!shouldKeep(entry.url)) return;
                    window.__mexcAutomationNetworkProbe.push({
                        ...entry,
                        ts: new Date().toISOString()
                    });
                    if (window.__mexcAutomationNetworkProbe.length > 80) {
                        window.__mexcAutomationNetworkProbe.shift();
                    }
                } catch (_) {}
            };
            const originalFetch = window.fetch;
            if (typeof originalFetch === 'function') {
                window.fetch = async (...args) => {
                    const started = Date.now();
                    const request = args[0];
                    const url = typeof request === 'string' ? request : request?.url;
                    const method = args[1]?.method || request?.method || 'GET';
                    try {
                        const response = await originalFetch(...args);
                        let body = '';
                        try { body = await response.clone().text(); } catch (_) {}
                        pushEntry({
                            type: 'fetch',
                            url,
                            method,
                            status: response.status,
                            ok: response.ok,
                            ms: Date.now() - started,
                            body: String(body || '').slice(0, 2500)
                        });
                        return response;
                    } catch (error) {
                        pushEntry({
                            type: 'fetch',
                            url,
                            method,
                            ok: false,
                            ms: Date.now() - started,
                            error: String(error)
                        });
                        throw error;
                    }
                };
            }
            const OriginalXHR = window.XMLHttpRequest;
            if (OriginalXHR && OriginalXHR.prototype) {
                const originalOpen = OriginalXHR.prototype.open;
                const originalSend = OriginalXHR.prototype.send;
                OriginalXHR.prototype.open = function(method, url, ...rest) {
                    this.__mexcAutomationProbe = {method, url, started: Date.now()};
                    return originalOpen.call(this, method, url, ...rest);
                };
                OriginalXHR.prototype.send = function(...args) {
                    this.addEventListener('loadend', () => {
                        const probe = this.__mexcAutomationProbe || {};
                        let body = '';
                        try { body = String(this.responseText || '').slice(0, 2500); } catch (_) {}
                        pushEntry({
                            type: 'xhr',
                            url: probe.url,
                            method: probe.method,
                            status: this.status,
                            ok: this.status >= 200 && this.status < 400,
                            ms: Date.now() - (probe.started || Date.now()),
                            body
                        });
                    });
                    return originalSend.apply(this, args);
                };
            }
            return true;
            """
        )
        self._log_step("mexc_deposit_screenshot_network_probe_installed", installed=bool(installed))

    def _network_probe_snapshot(self) -> list[dict[str, Any]]:
        try:
            entries = self.driver.execute_script(
                """
                return (window.__mexcAutomationNetworkProbe || []).map((entry) => ({
                    type: entry.type,
                    method: entry.method,
                    url: String(entry.url || '').slice(0, 500),
                    status: entry.status,
                    ok: entry.ok,
                    ms: entry.ms,
                    ts: entry.ts,
                    error: entry.error,
                    body: String(entry.body || '').slice(0, 1200)
                }));
                """
            )
            return entries if isinstance(entries, list) else []
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_network_probe_snapshot_failed", error=str(exc))
            return []

    def _raise_if_running(self) -> None:
        self._raise_if_cancelled()
        self._raise_if_browser_closed()

    def _ensure_record_tab(self) -> None:
        self._raise_if_browser_closed()
        driver = self.driver
        if driver is None:
            raise RuntimeError("Browser is not started.")

        handles = list(driver.window_handles)
        if self._record_window_handle in handles:
            driver.switch_to.window(self._record_window_handle)
        else:
            self._record_window_handle = None
            original_handle = driver.current_window_handle if handles else None
            for handle in handles:
                try:
                    driver.switch_to.window(handle)
                    current_url = (driver.current_url or "").lower()
                except Exception:
                    continue
                if "mexc.com" in current_url and "/assets/record" in current_url:
                    self._record_window_handle = handle
                    break
            if not self._record_window_handle:
                if original_handle and original_handle in driver.window_handles:
                    driver.switch_to.window(original_handle)
                    driver.get(self.RECORD_URL)
                    self._record_window_handle = driver.current_window_handle
                else:
                    driver.switch_to.new_window("tab")
                    driver.get(self.RECORD_URL)
                    self._record_window_handle = driver.current_window_handle

        current_url = (driver.current_url or "").lower()
        if "mexc.com" not in current_url or "/assets/record" not in current_url:
            driver.get(self.RECORD_URL)

    def _wait_for_history_page(self, deposit: dict[str, Any], page_index: int) -> dict[str, Any]:
        deadline = time.time() + 30
        last_snapshot = {}
        while time.time() < deadline:
            self._raise_if_running()
            self._ensure_record_tab()
            snapshot = self.driver.execute_script(
                """
                const deposit = arguments[0] || {};
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none'
                        && Number(style.opacity || '1') > 0.05;
                };
                const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const amount = normalize(deposit.amount);
                const coin = normalize(deposit.coin);
                const coinBase = normalize(deposit.coin_base);
                const dateHints = (deposit.date_hints || []).map(normalize).filter(Boolean);
                const bodyText = normalize(document.body?.innerText || document.body?.textContent || '');
                const rows = [...document.querySelectorAll('tr,[role="row"],.ant-table-row,[class*="row"],[class*="record"],li')]
                    .filter(visible)
                    .map((element) => normalize(element.innerText || element.textContent))
                    .filter(Boolean)
                    .slice(0, 80);
                const hasAmount = amount && bodyText.includes(amount);
                const hasCoin = (coin && bodyText.includes(coin)) || (coinBase && bodyText.includes(coinBase));
                const hasDate = dateHints.some((hint) => bodyText.includes(hint));
                const hasEmptyState = /no data|no records|empty|nothing found/i.test(bodyText);
                const hasTargetHint = Boolean(hasAmount && (hasCoin || hasDate));
                const hasHistorySurface = rows.length > 0 || hasEmptyState || hasTargetHint;
                return {
                    ready: Boolean(hasHistorySurface),
                    hasAmount,
                    hasCoin,
                    hasDate,
                    hasEmptyState,
                    rowCount: rows.length,
                    url: window.location.href,
                    title: document.title,
                    bodyHint: bodyText.slice(0, 1500),
                    rows,
                };
                """,
                deposit,
            )
            last_snapshot = snapshot if isinstance(snapshot, dict) else {}
            if last_snapshot.get("ready"):
                self._log_step("mexc_deposit_screenshot_history_ready", snapshot={
                    "has_amount": last_snapshot.get("hasAmount"),
                    "has_coin": last_snapshot.get("hasCoin"),
                    "has_date": last_snapshot.get("hasDate"),
                    "row_count": last_snapshot.get("rowCount"),
                    "page": page_index,
                    "url": last_snapshot.get("url"),
                })
                return last_snapshot
            self.control.wait(1)

        self._write_probe("rk_deposit_screenshot_history_timeout.json", last_snapshot)
        self._log_step("mexc_deposit_screenshot_history_not_ready", snapshot=last_snapshot)
        return last_snapshot

    def _open_matching_withdrawal_details(self, deposit: dict[str, Any]):
        visited_pages: list[dict[str, Any]] = []
        for page_index in range(1, self.MAX_WITHDRAWAL_PAGES + 1):
            self._raise_if_running()
            self._ensure_record_tab()
            page_snapshot = self._wait_for_history_page(deposit, page_index)
            candidates = self._collect_withdrawal_candidates(deposit)
            visited_pages.append({
                "page": page_index,
                "snapshot": self._compact_history_snapshot(page_snapshot),
                "candidate_count": len(candidates),
                "candidates": [
                    {
                        "score": item.get("score"),
                        "matched": item.get("matched"),
                        "identityMatched": item.get("identityMatched"),
                        "amountMatched": item.get("amountMatched"),
                        "text": item.get("text", "")[:500],
                    }
                    for item in candidates[:20]
                ],
            })
            self._log_step(
                "mexc_deposit_screenshot_page_scanned",
                page=page_index,
                candidate_count=len(candidates),
            )

            for candidate_index, candidate in enumerate(candidates, start=1):
                keep_details_open = False
                try:
                    self._raise_if_running()
                    self._ensure_record_tab()
                    clicked = self._click_withdrawal_candidate(candidate.get("element"), deposit)
                    if not clicked:
                        continue
                    self._log_step(
                        "mexc_deposit_screenshot_row_clicked",
                        page=page_index,
                        candidate=candidate_index,
                        score=candidate.get("score"),
                        matched=candidate.get("matched"),
                        row_text=str(candidate.get("text") or "")[:500],
                    )
                    if self._is_exact_identity_candidate(candidate):
                        details_root = self._wait_for_details_root_with_foreground_assist(
                            deposit,
                            page=page_index,
                            candidate=candidate_index,
                        )
                    else:
                        details_root = self._wait_for_details_root(deposit)
                    verification = self._verify_details_root(details_root, deposit)
                    if verification.get("matches"):
                        keep_details_open = True
                        return details_root
                    self._write_probe(
                        "rk_deposit_screenshot_details_mismatch.json",
                        {
                            "deposit": self._deposit_probe_payload(deposit),
                            "page": page_index,
                            "candidate": candidate_index,
                            "verification": verification,
                            "row_text": str(candidate.get("text") or "")[:1500],
                        },
                    )
                    self._log_step(
                        "mexc_deposit_screenshot_details_mismatch",
                        page=page_index,
                        candidate=candidate_index,
                        reason=verification.get("reason"),
                        score=verification.get("score"),
                    )
                except Exception as exc:
                    if self.cancel_event.is_set() or self.browser_is_closed():
                        raise
                    self._log_step(
                        "mexc_deposit_screenshot_candidate_failed",
                        page=page_index,
                        candidate=candidate_index,
                        error=str(exc),
                    )
                    if self._is_exact_identity_candidate(candidate):
                        self._write_probe(
                            "rk_deposit_screenshot_details_open_failed.json",
                            {
                                "deposit": self._deposit_probe_payload(deposit),
                                "page": page_index,
                                "candidate": candidate_index,
                                "error": str(exc),
                                "row_text": str(candidate.get("text") or "")[:1500],
                                "matched": candidate.get("matched"),
                                "score": candidate.get("score"),
                                "network": self._network_probe_snapshot(),
                            },
                        )
                        raise RuntimeError(
                            "Matching withdrawal row was found, but MEXC details did not open in background mode."
                        ) from exc
                finally:
                    if not keep_details_open:
                        self._close_details_modal()

            if not self._go_to_next_withdrawal_page(page_index):
                break

        probe = {
            "reason": "verified_details_not_found",
            "criteria": self._deposit_probe_payload(deposit),
            "pages": visited_pages,
        }
        self._write_probe("rk_deposit_screenshot_probe.json", probe)
        self._log_step("mexc_deposit_screenshot_row_not_found", result=probe)
        raise RuntimeError(
            "Matching withdrawal details were not found on MEXC after checking withdrawal history pages."
        )

    def _collect_withdrawal_candidates(self, deposit: dict[str, Any]) -> list[dict[str, Any]]:
        self._raise_if_running()
        result = self.driver.execute_script(
            """
            const deposit = arguments[0] || {};
            const maxCandidates = Number(arguments[1] || 10);
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && Number(style.opacity || '1') > 0.05;
            };
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const tx = normalize(deposit.tx_id || deposit.txId);
            const address = normalize(deposit.address);
            const amount = normalize(deposit.amount);
            const coin = normalize(deposit.coin);
            const coinBase = normalize(deposit.coin_base);
            const network = normalize(deposit.network);
            const dateHints = (deposit.date_hints || []).map(normalize).filter(Boolean);
            const addressHints = (deposit.address_hints || []).map(normalize).filter(Boolean);
            const txHints = (deposit.tx_hints || []).map(normalize).filter(Boolean);
            const hasDate = (text) => dateHints.some((hint) => hint && text.includes(hint));
            const hasAddressHint = (text) => addressHints.some((hint) => hint && text.includes(hint));
            const hasTxHint = (text) => txHints.some((hint) => hint && text.includes(hint));
            const requiresIdentity = Boolean(tx || address);

            const rowSelectors = [
                'tr',
                '[role="row"]',
                '.ant-table-row',
                '[data-row-key]',
                '[class*="table-row"]',
                '[class*="Table_row"]',
                '[class*="row"]',
                '[class*="Row"]',
                '[class*="record"]',
                '.ant-list-item',
                '[class*="list-item"]',
                'li'
            ];
            let rows = [...document.querySelectorAll(rowSelectors.join(','))]
                .filter(visible)
                .map((element) => {
                    const text = normalize(element.innerText || element.textContent);
                    let score = 0;
                    const matched = [];
                    const fullTxMatched = Boolean(tx && text.includes(tx));
                    const txHintMatched = hasTxHint(text);
                    const fullAddressMatched = Boolean(address && text.includes(address));
                    const addressHintMatched = hasAddressHint(text);
                    const amountMatched = Boolean(amount && text.includes(amount));
                    const coinMatched = Boolean(coin && text.includes(coin));
                    const coinBaseMatched = Boolean(coinBase && text.includes(coinBase));
                    const networkMatched = Boolean(network && text.includes(network));
                    const dateMatched = hasDate(text);
                    if (fullTxMatched) { score += 110; matched.push('tx_id'); }
                    if (txHintMatched) { score += 85; matched.push('tx_hint'); }
                    if (fullAddressMatched) { score += 75; matched.push('address'); }
                    if (addressHintMatched) { score += 65; matched.push('address_hint'); }
                    if (amountMatched) { score += 15; matched.push('amount'); }
                    if (coinMatched) { score += 8; matched.push('coin'); }
                    if (coinBaseMatched) { score += 8; matched.push('coin_base'); }
                    if (networkMatched) { score += 4; matched.push('network'); }
                    if (dateMatched) { score += 6; matched.push('date'); }
                    if (/success|completed|complete|confirmed|withdraw|withdrawal|send/.test(text)) score += 1;
                    const rect = element.getBoundingClientRect();
                    const identityMatched = fullTxMatched || txHintMatched || fullAddressMatched || addressHintMatched;
                    const fallbackMatched = amountMatched
                        && (coinMatched || coinBaseMatched)
                        && (networkMatched || dateMatched);
                    return {
                        element,
                        text,
                        score,
                        matched,
                        identityMatched,
                        fallbackMatched,
                        amountMatched,
                        area: rect.width * rect.height
                    };
                })
                .filter((item) => item.text.length <= 1800)
                .filter((item) => requiresIdentity ? item.identityMatched : item.fallbackMatched)
                .filter((item) => item.score >= (requiresIdentity ? 60 : 26));
            if (requiresIdentity && amount) {
                const amountIdentityRows = rows.filter((item) => item.amountMatched);
                if (amountIdentityRows.length) rows = amountIdentityRows;
            }
            return rows
                .sort((left, right) => {
                    if (right.score !== left.score) return right.score - left.score;
                    return left.area - right.area;
                })
                .slice(0, maxCandidates);
            """,
            deposit,
            self.MAX_CANDIDATES_PER_PAGE,
        )
        return result if isinstance(result, list) else []

    def _is_exact_identity_candidate(self, candidate: dict[str, Any]) -> bool:
        return bool(candidate.get("identityMatched") and candidate.get("amountMatched"))

    def _details_root_present(self, deposit: dict[str, Any]) -> bool:
        try:
            return self._find_details_root(deposit) is not None
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_details_presence_check_failed", error=str(exc))
            return False

    def _bring_record_page_to_front(self, reason: str) -> None:
        self._ensure_record_tab()
        try:
            window = self.driver.execute_cdp_cmd("Browser.getWindowForTarget", {})
            window_id = window.get("windowId") if isinstance(window, dict) else None
            bounds = window.get("bounds") if isinstance(window, dict) else None
            if window_id and isinstance(bounds, dict) and bounds.get("windowState") == "minimized":
                self.driver.execute_cdp_cmd("Browser.setWindowBounds", {
                    "windowId": window_id,
                    "bounds": {"windowState": "normal"},
                })
            self._log_step("mexc_deposit_screenshot_browser_window_state", reason=reason, bounds=bounds)
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_browser_window_state_failed", reason=reason, error=str(exc))
        try:
            self.driver.execute_cdp_cmd("Page.enable", {})
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_cdp_page_enable_failed", reason=reason, error=str(exc))
        try:
            self.driver.execute_cdp_cmd("Page.setWebLifecycleState", {"state": "active"})
            self._log_step("mexc_deposit_screenshot_cdp_lifecycle_active", reason=reason)
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_cdp_lifecycle_active_failed", reason=reason, error=str(exc))
        try:
            self.driver.execute_cdp_cmd("Emulation.setFocusEmulationEnabled", {"enabled": True})
            self._log_step("mexc_deposit_screenshot_cdp_focus_emulation", reason=reason)
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_cdp_focus_emulation_failed", reason=reason, error=str(exc))
        try:
            self.driver.execute_cdp_cmd("Page.bringToFront", {})
            self._log_step("mexc_deposit_screenshot_cdp_bring_to_front", reason=reason)
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_cdp_bring_to_front_failed", reason=reason, error=str(exc))

    def _click_withdrawal_candidate(self, row, deposit: dict[str, Any]) -> bool:
        if row is None:
            return False
        self._raise_if_running()
        self._bring_record_page_to_front("candidate_click")
        click_info = self.driver.execute_script(
            """
            const row = arguments[0];
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && Number(style.opacity || '1') > 0.05;
            };
            const detailCandidates = [...row.querySelectorAll('button,a,[role="button"],span,div')]
                .filter(visible)
                .filter((element) => /detail|details|view|more|txid|transaction/i.test(
                    element.innerText || element.textContent || element.getAttribute('aria-label') || ''
                ))
                .sort((left, right) => {
                    const lr = left.getBoundingClientRect();
                    const rr = right.getBoundingClientRect();
                return (lr.width * lr.height) - (rr.width * rr.height);
                });
            const target = detailCandidates[0]?.closest('button,a,[role="button"]') || detailCandidates[0] || row;
            target.scrollIntoView({ block: 'center', inline: 'center' });
            window.__mexcAutomationClickTarget = target;
            window.__mexcAutomationClickRow = row;
            if (typeof target.focus === 'function') {
                try { target.focus({ preventScroll: true }); } catch (_) { target.focus(); }
            }
            const rect = target.getBoundingClientRect();
            if (!rect.width || !rect.height) {
                return { ready: false, reason: 'target_has_no_rect' };
            }
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const clickX = Math.round(Math.min(Math.max(centerX, 1), window.innerWidth - 2));
            const clickY = Math.round(Math.min(Math.max(centerY, 1), window.innerHeight - 2));
            const dispatchSequence = (element) => {
                if (!element) return false;
                const init = {
                    bubbles: true,
                    cancelable: true,
                    composed: true,
                    view: window,
                    clientX: clickX,
                    clientY: clickY,
                    screenX: clickX,
                    screenY: clickY,
                    button: 0,
                    buttons: 1
                };
                try {
                    if (window.PointerEvent) {
                        element.dispatchEvent(new PointerEvent('pointerover', {...init, pointerId: 1, pointerType: 'mouse'}));
                        element.dispatchEvent(new PointerEvent('pointermove', {...init, pointerId: 1, pointerType: 'mouse'}));
                        element.dispatchEvent(new PointerEvent('pointerdown', {...init, pointerId: 1, pointerType: 'mouse'}));
                        element.dispatchEvent(new PointerEvent('pointerup', {...init, buttons: 0, pointerId: 1, pointerType: 'mouse'}));
                    }
                    element.dispatchEvent(new MouseEvent('mouseover', init));
                    element.dispatchEvent(new MouseEvent('mousemove', init));
                    element.dispatchEvent(new MouseEvent('mousedown', init));
                    element.dispatchEvent(new MouseEvent('mouseup', {...init, buttons: 0}));
                    element.dispatchEvent(new MouseEvent('click', {...init, buttons: 0}));
                    if (typeof element.click === 'function') element.click();
                    return true;
                } catch (_) {
                    return false;
                }
            };
            const syntheticTarget = dispatchSequence(target);
            const syntheticRow = target === row ? false : dispatchSequence(row);
            const pointElement = document.elementFromPoint(clickX, clickY);
            return {
                ready: true,
                x: clickX,
                y: clickY,
                rawX: Math.round(centerX),
                rawY: Math.round(centerY),
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                devicePixelRatio: window.devicePixelRatio || 1,
                visibilityState: document.visibilityState,
                hasFocus: document.hasFocus(),
                syntheticTarget,
                syntheticRow,
                targetTag: target.tagName,
                targetClass: String(target.className || '').slice(0, 160),
                pointTag: pointElement?.tagName || '',
                pointText: String(pointElement?.innerText || pointElement?.textContent || '').slice(0, 120),
                targetText: String(target.innerText || target.textContent || target.getAttribute('aria-label') || '').slice(0, 120),
                target
            };
            """,
            row,
        )
        if not isinstance(click_info, dict) or not click_info.get("ready"):
            self._log_step("mexc_deposit_screenshot_candidate_click_target_missing", result=click_info)
            return False

        self._log_step("mexc_deposit_screenshot_candidate_js_click_dispatched", result={
            key: value
            for key, value in click_info.items()
            if key != "target"
        })
        self.control.wait(1)
        self._raise_if_running()
        if self._details_root_present(deposit):
            return True

        try:
            evaluated = self.driver.execute_cdp_cmd(
                "Runtime.evaluate",
                {
                    "expression": """
                        (() => {
                            const target = window.__mexcAutomationClickTarget;
                            if (!target) return {clicked: false, reason: 'target_missing'};
                            target.scrollIntoView({block: 'center', inline: 'center'});
                            if (typeof target.focus === 'function') {
                                try { target.focus({preventScroll: true}); } catch (_) { target.focus(); }
                            }
                            target.click();
                            return {
                                clicked: true,
                                tag: target.tagName,
                                text: String(target.innerText || target.textContent || target.getAttribute('aria-label') || '').slice(0, 120),
                                visibilityState: document.visibilityState,
                                hasFocus: document.hasFocus()
                            };
                        })()
                    """,
                    "awaitPromise": True,
                    "userGesture": True,
                    "returnByValue": True,
                },
            )
            self._log_step("mexc_deposit_screenshot_candidate_runtime_user_gesture_click", result=evaluated)
            self.control.wait(1)
            self._raise_if_running()
            if self._details_root_present(deposit):
                return True
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_candidate_runtime_user_gesture_click_failed", error=str(exc))

        target_element = click_info.get("target")
        if target_element is not None:
            try:
                target_element.click()
                self._log_step("mexc_deposit_screenshot_candidate_webdriver_click_dispatched")
                self.control.wait(1)
                self._raise_if_running()
                if self._details_root_present(deposit):
                    return True
            except Exception as exc:
                self._log_step("mexc_deposit_screenshot_candidate_webdriver_click_failed", error=str(exc))

        self._bring_record_page_to_front("candidate_cdp_click")
        try:
            self.driver.execute_cdp_cmd("Page.enable", {})
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_click_cdp_page_enable_failed", error=str(exc))
        try:
            self.driver.execute_cdp_cmd("Page.bringToFront", {})
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_click_cdp_bring_to_front_failed", error=str(exc))

        x = int(click_info.get("x") or 0)
        y = int(click_info.get("y") or 0)
        if x <= 0 or y <= 0:
            self._log_step("mexc_deposit_screenshot_candidate_click_point_invalid", result=click_info)
            return False

        try:
            self.driver.execute_cdp_cmd(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": x, "y": y, "button": "none", "pointerType": "mouse"},
            )
            self.driver.execute_cdp_cmd(
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "buttons": 1,
                    "clickCount": 1,
                    "pointerType": "mouse",
                },
            )
            self.driver.execute_cdp_cmd(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": x,
                    "y": y,
                    "button": "left",
                    "buttons": 0,
                    "clickCount": 1,
                    "pointerType": "mouse",
                },
            )
            self._log_step(
                "mexc_deposit_screenshot_candidate_cdp_click_dispatched",
                x=x,
                y=y,
                target_text=str(click_info.get("targetText") or ""),
            )
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_candidate_cdp_click_failed", error=str(exc))
            return False
        self.control.wait(3)
        self._raise_if_running()
        return True

    def _wait_for_details_root_with_foreground_assist(
        self,
        deposit: dict[str, Any],
        *,
        page: int,
        candidate: int,
    ):
        root = self._wait_for_details_root(deposit, timeout=18, raise_on_timeout=False)
        if root is not None:
            return root

        state = self._page_visibility_snapshot()
        detail_api_seen = self._detail_api_seen()
        message = (
            "MEXC did not render the native withdrawal details modal while the browser tab was in background. "
            "Switch to the AdsPower MEXC window/tab now and leave the Details modal open; the automation is waiting."
        )
        self._log_step(
            "mexc_deposit_screenshot_foreground_required",
            deposit=self._deposit_label(deposit),
            page=page,
            candidate=candidate,
            visibility_state=state.get("visibilityState"),
            has_focus=state.get("hasFocus"),
            detail_api_seen=detail_api_seen,
            message=message,
        )

        deadline = time.time() + self.FOREGROUND_ASSIST_TIMEOUT_SECONDS
        last_wait_log = 0.0
        while time.time() < deadline:
            self._raise_if_running()
            root = self._find_details_root(deposit)
            if root is not None:
                self._log_step(
                    "mexc_deposit_screenshot_foreground_resumed",
                    deposit=self._deposit_label(deposit),
                    page=page,
                    candidate=candidate,
                    visibility_state=self._page_visibility_snapshot().get("visibilityState"),
                )
                return root
            now = time.time()
            if now - last_wait_log >= 20:
                last_wait_log = now
                self._log_step(
                    "mexc_deposit_screenshot_foreground_waiting",
                    deposit=self._deposit_label(deposit),
                    seconds_left=int(max(0, deadline - now)),
                    visibility_state=self._page_visibility_snapshot().get("visibilityState"),
                )
            self.control.wait(1)

        self._write_probe(
            "rk_deposit_screenshot_foreground_timeout.json",
            {
                "deposit": self._deposit_probe_payload(deposit),
                "page": page,
                "candidate": candidate,
                "visibility": self._page_visibility_snapshot(),
                "detail_api_seen": self._detail_api_seen(),
                "network": self._network_probe_snapshot(),
            },
        )
        raise RuntimeError(
            "MEXC native withdrawal details did not appear. Switch to the main MEXC AdsPower window/tab and retry."
        )

    def _wait_for_details_root(
        self,
        deposit: dict[str, Any],
        *,
        timeout: float = 25,
        raise_on_timeout: bool = True,
    ):
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._raise_if_running()
            root = self._find_details_root(deposit)
            if root is not None:
                return root
            self.control.wait(1)
        if not raise_on_timeout:
            return None
        raise RuntimeError(
            "Withdrawal details did not open. Open the withdrawal details manually in the main profile and retry."
        )

    def _page_visibility_snapshot(self) -> dict[str, Any]:
        try:
            result = self.driver.execute_script(
                """
                return {
                    visibilityState: document.visibilityState,
                    hidden: document.hidden,
                    hasFocus: document.hasFocus(),
                    url: window.location.href,
                    title: document.title,
                };
                """
            )
            return result if isinstance(result, dict) else {}
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_visibility_snapshot_failed", error=str(exc))
            return {}

    def _detail_api_seen(self) -> bool:
        return any("/api/platform/withdraw/v2/detail/" in str(entry.get("url") or "") for entry in self._network_probe_snapshot())

    def _find_details_root(self, deposit: dict[str, Any]):
        return self.driver.execute_script(
            """
            const deposit = arguments[0] || {};
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && Number(style.opacity || '1') > 0.05;
            };
            const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const tx = normalize(deposit.tx_id || deposit.txId);
            const address = normalize(deposit.address);
            const amount = normalize(deposit.amount);
            const coin = normalize(deposit.coin);
            const coinBase = normalize(deposit.coin_base);
            const roots = [...document.querySelectorAll([
                '.ant-modal-content',
                '.ant-drawer-content',
                '[role="dialog"]'
            ].join(','))]
                .filter(visible)
                .map((element) => {
                    const text = normalize(element.innerText || element.textContent);
                    const rect = element.getBoundingClientRect();
                    const cls = String(element.className || '').toLowerCase();
                    const shell = element.closest('.ant-modal,.ant-drawer,[role="dialog"]');
                    const shellClass = String(shell?.className || '').toLowerCase();
                    const hasDetailsText = /withdrawal details|withdrawal address|withdrawal completed|withdrawal request submitted|txid/.test(text);
                    const hasGlobalNavigation = /buy crypto|markets|event center|funding history|overview spot/.test(text);
                    const nearlyFullViewport = rect.width >= window.innerWidth * 0.9
                        && rect.height >= window.innerHeight * 0.8;
                    let score = 0;
                    let depositScore = 0;
                    if (/withdrawal details/.test(text)) score += 20;
                    if (/withdrawal address|txid|withdrawal completed|transaction hash/.test(text)) score += 8;
                    if (/detail|details|withdrawal|transaction|txid|hash/.test(text)) score += 3;
                    if (/ant-modal-content|ant-drawer-content/.test(cls)) score += 6;
                    if (/ant-modal|ant-drawer/.test(shellClass)) score += 4;
                    if (tx && text.includes(tx)) depositScore += 12;
                    if (address && text.includes(address)) depositScore += 10;
                    if (amount && text.includes(amount)) depositScore += 4;
                    if (coin && text.includes(coin)) depositScore += 2;
                    if (coinBase && text.includes(coinBase)) depositScore += 2;
                    return {
                        element,
                        score: score + depositScore,
                        depositScore,
                        hasDetailsText,
                        hasGlobalNavigation,
                        nearlyFullViewport
                    };
                })
                .filter((item) => item.hasDetailsText)
                .filter((item) => !item.hasGlobalNavigation)
                .filter((item) => !item.nearlyFullViewport || item.score >= 30)
                .sort((left, right) => {
                    if (right.score !== left.score) return right.score - left.score;
                    const lr = left.element.getBoundingClientRect();
                    const rr = right.element.getBoundingClientRect();
                    return (lr.width * lr.height) - (rr.width * rr.height);
                });
            return roots[0]?.element || null;
            """,
            deposit,
        )

    def _verify_details_root(self, details_root, deposit: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.driver.execute_script(
                """
                const element = arguments[0];
                const deposit = arguments[1] || {};
                const normalize = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                const text = normalize(element?.innerText || element?.textContent || '');
                const tx = normalize(deposit.tx_id || deposit.txId);
                const address = normalize(deposit.address);
                const amount = normalize(deposit.amount);
                const coin = normalize(deposit.coin);
                const coinBase = normalize(deposit.coin_base);
                const network = normalize(deposit.network);
                const dateHints = (deposit.date_hints || []).map(normalize).filter(Boolean);
                const looksLikeDetails = /withdrawal details|withdrawal address|withdrawal completed|withdrawal request submitted|txid/.test(text);
                const looksLikeHistoryPage = /buy crypto|markets|event center|funding history|overview spot/.test(text);
                const hasDate = dateHints.some((hint) => text.includes(hint));
                const hasTx = Boolean(tx && text.includes(tx));
                const hasAddress = Boolean(address && text.includes(address));
                const hasAmount = Boolean(amount && text.includes(amount));
                const hasCoin = Boolean((coin && text.includes(coin)) || (coinBase && text.includes(coinBase)));
                const hasNetwork = Boolean(network && text.includes(network));
                let score = 0;
                if (hasTx) score += 100;
                if (hasAddress) score += 70;
                if (hasAmount) score += 15;
                if (hasCoin) score += 10;
                if (hasNetwork) score += 4;
                if (hasDate) score += 6;

                let matches = false;
                let reason = 'fallback_combo_not_matched';
                if (!looksLikeDetails || looksLikeHistoryPage) {
                    matches = false;
                    reason = looksLikeHistoryPage ? 'history_page_not_details' : 'details_markers_missing';
                } else if (tx) {
                    matches = hasTx;
                    reason = matches ? 'tx_id_matched' : 'tx_id_missing_in_details';
                } else if (address) {
                    matches = hasAddress;
                    reason = matches ? 'address_matched' : 'address_missing_in_details';
                } else {
                    matches = hasAmount && hasCoin && (hasNetwork || hasDate);
                    reason = matches ? 'amount_coin_context_matched' : 'weak_details_match';
                }
                return {
                    matches,
                    reason,
                    score,
                    hasTx,
                    hasAddress,
                    hasAmount,
                    hasCoin,
                    hasNetwork,
                    hasDate,
                    looksLikeDetails,
                    looksLikeHistoryPage,
                    text: text.slice(0, 1200)
                };
                """,
                details_root,
                deposit,
            )
            self._log_step("mexc_deposit_screenshot_details_verified", result=result)
            return result if isinstance(result, dict) else {"matches": False, "reason": "invalid_verification_result"}
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_details_verify_failed", error=str(exc))
            return {"matches": False, "reason": "details_verify_exception", "error": str(exc)}

    def _go_to_next_withdrawal_page(self, page_index: int) -> bool:
        self._raise_if_running()
        result = self.driver.execute_script(
            """
            const visible = (element) => {
                if (!element) return false;
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return rect.width > 0 && rect.height > 0
                    && style.visibility !== 'hidden'
                    && style.display !== 'none'
                    && Number(style.opacity || '1') > 0.05;
            };
            const disabled = (element) => {
                const cls = String(element.className || '').toLowerCase();
                return element.disabled
                    || element.getAttribute('aria-disabled') === 'true'
                    || cls.includes('disabled');
            };
            const describe = (element) => [
                element.innerText,
                element.textContent,
                element.getAttribute('aria-label'),
                element.getAttribute('title'),
                element.className
            ].filter(Boolean).join(' ');

            const selectors = [
                '.ant-pagination-next',
                '[aria-label="Next Page"]',
                '[title="Next Page"]',
                'button',
                'li',
                'a',
                '[role="button"]'
            ];
            const candidates = [...document.querySelectorAll(selectors.join(','))]
                .filter(visible)
                .filter((element) => /next|next page|›|>|pagination-next/i.test(describe(element)))
                .map((element) => element.closest('button,a,li,[role="button"]') || element)
                .filter((element, index, items) => items.indexOf(element) === index)
                .filter((element) => !disabled(element));
            const target = candidates[0];
            if (!target) {
                window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' });
                return { clicked: false, reason: 'next_not_found' };
            }
            target.scrollIntoView({ block: 'center', inline: 'center' });
            target.click();
            return { clicked: true };
            """
        )
        clicked = isinstance(result, dict) and bool(result.get("clicked"))
        self._log_step("mexc_deposit_screenshot_next_page", page=page_index, result=result)
        if clicked:
            self.control.wait(3)
            self._raise_if_running()
        return clicked

    def _compact_history_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            return {}
        return {
            "hasAmount": bool(snapshot.get("hasAmount")),
            "hasCoin": bool(snapshot.get("hasCoin")),
            "hasDate": bool(snapshot.get("hasDate")),
            "hasEmptyState": bool(snapshot.get("hasEmptyState")),
            "rowCount": snapshot.get("rowCount"),
            "url": snapshot.get("url"),
            "title": snapshot.get("title"),
            "bodyHint": str(snapshot.get("bodyHint") or "")[:1500],
            "rows": [str(row)[:500] for row in (snapshot.get("rows") or [])[:20]],
        }

    def _deposit_probe_payload(self, deposit: dict[str, Any]) -> dict[str, Any]:
        address_hints = deposit.get("address_hints") or []
        tx_hints = deposit.get("tx_hints") or []
        return {
            "amount": deposit.get("amount"),
            "coin": deposit.get("coin"),
            "coin_base": deposit.get("coin_base"),
            "network": deposit.get("network"),
            "address": deposit.get("address"),
            "tx_id": deposit.get("tx_id") or deposit.get("txId"),
            "date_hints": deposit.get("date_hints") or [],
            "address_hints_count": len(address_hints),
            "address_hints_sample": address_hints[:8],
            "tx_hints_count": len(tx_hints),
            "tx_hints_sample": tx_hints[:8],
        }

    def _save_details_screenshot(self, details_root, screenshot_path: Path) -> None:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        self._wait_for_stable_details_rect(details_root)
        if self._save_viewport_cropped_details_screenshot(details_root, screenshot_path):
            return
        raise RuntimeError("Could not save a cropped withdrawal details screenshot.")

    def _wait_for_stable_details_rect(self, details_root, timeout: float = 3.0) -> None:
        deadline = time.time() + timeout
        previous: dict[str, Any] | None = None
        stable_count = 0
        while time.time() < deadline:
            self._raise_if_running()
            rect = self.driver.execute_script(
                """
                const element = arguments[0];
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                return {
                    left: Math.round(rect.left),
                    top: Math.round(rect.top),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    opacity: Number(style.opacity || '1')
                };
                """,
                details_root,
            )
            if (
                isinstance(rect, dict)
                and previous
                and rect.get("left") == previous.get("left")
                and rect.get("top") == previous.get("top")
                and rect.get("width") == previous.get("width")
                and rect.get("height") == previous.get("height")
                and float(rect.get("opacity") or 0) >= 0.95
            ):
                stable_count += 1
                if stable_count >= 2:
                    return
            else:
                stable_count = 0
            previous = rect if isinstance(rect, dict) else None
            self.control.wait(0.2)

    def _screenshot_is_probably_full_viewport(self, screenshot_path: Path) -> bool:
        try:
            image = Image.open(screenshot_path)
            viewport = self.driver.execute_script(
                """
                return {
                    width: window.innerWidth * (window.devicePixelRatio || 1),
                    height: window.innerHeight * (window.devicePixelRatio || 1)
                };
                """
            )
            viewport_width = float(viewport.get("width") or 0) if isinstance(viewport, dict) else 0
            viewport_height = float(viewport.get("height") or 0) if isinstance(viewport, dict) else 0
            if viewport_width <= 0 or viewport_height <= 0:
                return False
            return image.width >= viewport_width * 0.88 and image.height >= viewport_height * 0.78
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_size_check_failed", error=str(exc))
            return False

    def _save_viewport_cropped_details_screenshot(self, details_root, screenshot_path: Path) -> bool:
        try:
            rect = self.driver.execute_script(
                """
                const element = arguments[0];
                const rect = element.getBoundingClientRect();
                return {
                    x: Math.max(0, rect.left),
                    y: Math.max(0, rect.top),
                    width: rect.width,
                    height: rect.height,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight,
                    dpr: window.devicePixelRatio || 1
                };
                """,
                details_root,
            )
            if not isinstance(rect, dict):
                return False
            width = float(rect.get("width") or 0)
            height = float(rect.get("height") or 0)
            if width < 120 or height < 120:
                return False

            viewport_width = float(rect.get("viewportWidth") or 0)
            viewport_height = float(rect.get("viewportHeight") or 0)
            if viewport_width <= 0 or viewport_height <= 0:
                return False

            png = self._capture_active_tab_viewport_png()
            image = Image.open(BytesIO(png))
            scale_x = image.width / viewport_width
            scale_y = image.height / viewport_height
            left = int(max(0, float(rect.get("x") or 0) * scale_x))
            top = int(max(0, float(rect.get("y") or 0) * scale_y))
            right = int(min(image.width, left + width * scale_x))
            bottom = int(min(image.height, top + height * scale_y))
            if right <= left or bottom <= top:
                return False
            if (right - left) >= image.width * 0.88 and (bottom - top) >= image.height * 0.78:
                self._log_step("mexc_deposit_screenshot_viewport_full_crop_rejected")
                return False
            cropped = image.crop((left, top, right, bottom))
            cropped.save(screenshot_path)
            if self._screenshot_is_probably_full_viewport(screenshot_path):
                self._log_step("mexc_deposit_screenshot_viewport_full_viewport_file_rejected", path=str(screenshot_path))
                try:
                    screenshot_path.unlink()
                except Exception:
                    pass
                return False
            self._log_step(
                "mexc_deposit_screenshot_viewport_cropped",
                rect={
                    "left": left,
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "image_width": image.width,
                    "image_height": image.height,
                    "scale_x": scale_x,
                    "scale_y": scale_y,
                    "source": "cdp_viewport",
                },
            )
            return True
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_viewport_crop_failed", error=str(exc))
            return False

    def _capture_active_tab_viewport_png(self) -> bytes:
        self._raise_if_running()
        self._log_step("mexc_deposit_screenshot_capture_start", method="cdp_viewport")
        self._bring_record_page_to_front("capture_screenshot")
        self.control.wait(0.35)
        self._log_step("mexc_deposit_screenshot_frame_wait_done", method="sleep_after_cdp_bring_to_front")

        captured = self.driver.execute_cdp_cmd(
            "Page.captureScreenshot",
            {
                "format": "png",
                "fromSurface": True,
                "captureBeyondViewport": False,
                "optimizeForSpeed": True,
            },
        )
        data = captured.get("data") if isinstance(captured, dict) else ""
        if not data:
            raise RuntimeError("Chrome DevTools did not return screenshot data.")
        self._log_step("mexc_deposit_screenshot_capture_done", method="cdp_viewport")
        return base64.b64decode(data)

    def _close_details_modal(self) -> None:
        if not self.driver:
            return
        try:
            closed = self.driver.execute_script(
                """
                const visible = (element) => {
                    if (!element) return false;
                    const rect = element.getBoundingClientRect();
                    const style = window.getComputedStyle(element);
                    return rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden'
                        && style.display !== 'none';
                };
                const roots = [...document.querySelectorAll('.ant-modal-content,.ant-drawer-content,[role="dialog"]')]
                    .filter(visible);
                const root = roots[0];
                if (!root) return false;
                const candidates = [...root.querySelectorAll('button,[role="button"],span,svg')]
                    .filter(visible)
                    .filter((element) => {
                        const text = element.innerText || element.textContent || element.getAttribute('aria-label') || '';
                        const cls = element.className && String(element.className);
                        return /close|закрити|×/i.test(text) || /close/i.test(cls || '');
                    });
                const target = candidates[0]?.closest('button,[role="button"]') || candidates[0];
                if (target) {
                    target.click();
                    return true;
                }
                return false;
                """
            )
            if not closed:
                self.driver.execute_script("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}));")
            self.control.wait(1)
        except Exception as exc:
            self._log_step("mexc_deposit_screenshot_close_modal_failed", error=str(exc))

    def _write_probe(self, filename: str, payload: dict[str, Any]) -> None:
        try:
            path = self.account_dir / filename
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
