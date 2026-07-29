from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class BrowserConnection:
    selenium_address: str
    puppeteer_ws: str
    webdriver_path: str
    debug_port: str


class AdsPowerClient:
    BASE_URL = "http://local.adspower.net:50401"
    FALLBACK_BASE_URLS = (
        "http://127.0.0.1:50401",
        "http://local.adspower.net:50325",
        "http://127.0.0.1:50325",
    )
    SENSITIVE_KEYS = {
        "api_key",
        "authorization",
        "password",
        "token",
        "secret",
        "secret_key",
    }
    RATE_LIMIT_TEXT = "too many request"

    def __init__(self, api_key: str = "", base_url: str | None = None):
        self.api_key = api_key
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False

    def _headers(self) -> dict:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def _base_url_candidates(self) -> list[str]:
        urls = [self.base_url]
        for url in self.FALLBACK_BASE_URLS:
            clean_url = url.rstrip("/")
            if clean_url not in urls:
                urls.append(clean_url)
        return urls

    def _safe_payload(self, value: Any) -> Any:
        if isinstance(value, dict):
            clean = {}
            for key, item in value.items():
                key_text = str(key).lower()
                if any(sensitive in key_text for sensitive in self.SENSITIVE_KEYS):
                    clean[key] = "***"
                else:
                    clean[key] = self._safe_payload(item)
            return clean
        if isinstance(value, list):
            return [self._safe_payload(item) for item in value]
        return value

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_data: dict | None = None,
        timeout: int = 10,
    ) -> dict | None:
        last_error: Exception | None = None
        for base_url in self._base_url_candidates():
            url = f"{base_url}{path}"
            started_at = time.perf_counter()
            logger.info(
                "AdsPower API request method=%s url=%s params=%s json=%s timeout=%ss",
                method,
                url,
                self._safe_payload(params or {}),
                self._safe_payload(json_data or {}),
                timeout,
            )
            try:
                payload = None
                elapsed_ms = 0
                resp = None
                for attempt in range(1, 4):
                    resp = self.session.request(
                        method,
                        url,
                        params=params,
                        json=json_data,
                        headers=self._headers(),
                        timeout=timeout,
                    )
                    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                    if resp.status_code == 404:
                        logger.warning(
                            "AdsPower API endpoint not found method=%s url=%s elapsed_ms=%s text=%r",
                            method,
                            url,
                            elapsed_ms,
                            resp.text[:300],
                        )
                        return None
                    try:
                        payload = resp.json()
                    except ValueError:
                        logger.error(
                            "AdsPower API invalid JSON method=%s url=%s status=%s elapsed_ms=%s text=%r",
                            method,
                            url,
                            resp.status_code,
                            elapsed_ms,
                            resp.text[:300],
                        )
                        return None

                    msg = str(payload.get("msg", ""))
                    if (
                        payload.get("code") == 0
                        or self.RATE_LIMIT_TEXT not in msg.lower()
                        or attempt == 3
                    ):
                        break

                    logger.warning(
                        "AdsPower API rate limited method=%s url=%s attempt=%s msg=%s; retrying",
                        method,
                        url,
                        attempt,
                        msg,
                    )
                    time.sleep(1.2)

                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                logger.info(
                    "AdsPower API response method=%s url=%s http_status=%s elapsed_ms=%s code=%s msg=%s data_keys=%s",
                    method,
                    url,
                    resp.status_code if resp else "",
                    elapsed_ms,
                    payload.get("code"),
                    payload.get("msg"),
                    sorted((payload.get("data") or {}).keys())
                    if isinstance(payload.get("data"), dict)
                    else type(payload.get("data")).__name__,
                )

                if payload.get("code") != 0:
                    logger.warning(
                        "AdsPower API business error method=%s path=%s code=%s msg=%s",
                        method,
                        path,
                        payload.get("code"),
                        payload.get("msg"),
                    )
                    return None

                self.base_url = base_url
                data = payload.get("data")
                return data if data is not None else {}
            except requests.RequestException as exc:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                last_error = exc
                logger.warning(
                    "AdsPower API connection failed method=%s url=%s elapsed_ms=%s error=%s",
                    method,
                    url,
                    elapsed_ms,
                    exc,
                )

        logger.error(
            "AdsPower API unavailable path=%s tried=%s last_error=%s",
            path,
            self._base_url_candidates(),
            last_error,
        )
        return None

    def _get(
        self,
        path: str,
        params: dict | None = None,
        *,
        timeout: int = 10,
    ) -> dict | None:
        return self._request("GET", path, params=params, timeout=timeout)

    def _post(self, path: str, json_data: dict | None = None) -> dict | None:
        return self._request("POST", path, json_data=json_data)

    # ── Health ────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._get("/status", timeout=3) is not None

    # ── Browser operations ───────────────────────────────────

    def start_browser(
        self,
        profile_id: str,
        *,
        headless: bool = False,
        launch_args: list[str] | None = None,
    ) -> BrowserConnection | None:
        params: dict = {"user_id": profile_id}
        if headless:
            params["headless"] = 1
        if launch_args:
            params["launch_args"] = str(launch_args)
        data = self._get("/api/v1/browser/start", params)
        if data is None:
            return None
        ws = data.get("ws", {})
        conn = BrowserConnection(
            selenium_address=ws.get("selenium", ""),
            puppeteer_ws=ws.get("puppeteer", ""),
            webdriver_path=data.get("webdriver", ""),
            debug_port=data.get("debug_port", ""),
        )
        logger.info(
            "AdsPower browser start result profile_id=%s selenium=%s webdriver_path=%s debug_port=%s puppeteer_ws=%s",
            profile_id,
            conn.selenium_address,
            conn.webdriver_path,
            conn.debug_port,
            conn.puppeteer_ws,
        )
        return conn

    def stop_browser(self, profile_id: str) -> bool:
        return self._get("/api/v1/browser/stop", {"user_id": profile_id}) is not None

    def is_browser_active(self, profile_id: str) -> bool:
        data = self._get("/api/v1/browser/active", {"user_id": profile_id})
        if data is None:
            return False
        return data.get("status") == "Active"

    # ── Profile management ───────────────────────────────────

    def list_profiles(
        self,
        *,
        group_id: str | None = None,
        page: int = 1,
        limit: int = 100,
    ) -> list[dict]:
        params: dict = {"page": page, "page_size": limit}
        if group_id:
            params["group_id"] = group_id
        data = self._get("/api/v1/user/list", params)
        if data is None:
            return []
        return data.get("list", [])

    def list_all_profiles(self) -> list[dict]:
        all_profiles: list[dict] = []
        page = 1
        while True:
            batch = self.list_profiles(page=page, limit=100)
            if not batch:
                break
            all_profiles.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_profiles

    def find_profile_by_name(self, name: str) -> dict | None:
        profiles = self.list_all_profiles()
        for p in profiles:
            if p.get("name") == name:
                return p
        return None

    def create_profile(
        self,
        *,
        name: str,
        group_id: str = "0",
        fingerprint_config: dict | None = None,
        user_proxy_config: dict | None = None,
        proxyid: str | None = None,
        remark: str = "",
    ) -> dict | None:
        body: dict = {
            "name": name,
            "group_id": group_id,
            "fingerprint_config": fingerprint_config or {"automatic_timezone": 1},
        }
        if proxyid:
            body["proxyid"] = proxyid
        elif user_proxy_config:
            body["user_proxy_config"] = user_proxy_config
        else:
            body["user_proxy_config"] = {"proxy_soft": "no_proxy"}
        if remark:
            body["remark"] = remark
        return self._post("/api/v1/user/create", body)

    def update_profile(self, profile_id: str, **kwargs) -> bool:
        body = {"user_id": profile_id, **kwargs}
        return self._post("/api/v1/user/update", body) is not None

    def delete_profiles(self, profile_ids: list[str]) -> bool:
        return self._post("/api/v1/user/delete", {"user_ids": profile_ids}) is not None

    # ── Groups ───────────────────────────────────────────────

    def list_groups(
        self,
        *,
        group_name: str | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict]:
        params: dict = {"page": page, "page_size": page_size}
        if group_name:
            params["group_name"] = group_name
        data = self._get("/api/v1/group/list", params)
        if data is None:
            return []
        return data.get("list", [])

    def create_group(self, name: str) -> dict | None:
        return self._post("/api/v1/group/create", {"group_name": name})

    # ── Proxies ───────────────────────────────────────────────────────────────

    def list_saved_proxies(self, *, page: int = 1, limit: int = 50) -> list[dict]:
        data = self._post("/api/v2/proxy-list/list", {"page": page, "limit": limit})
        if data is None:
            return []
        return data.get("list", [])

    # ── Tags ─────────────────────────────────────────────────

    def list_tags(
        self,
        *,
        ids: list[str] | None = None,
        page: int = 1,
        limit: int = 200,
    ) -> list[dict]:
        params: dict = {"page": page, "limit": limit}
        if ids:
            params["ids"] = ids
        data = self._get("/api/v1/tag/list", params)
        if data is None:
            return []
        return data.get("list", [])

    def list_all_tags(self) -> list[dict]:
        all_tags: list[dict] = []
        page = 1
        while True:
            batch = self.list_tags(page=page, limit=200)
            if not batch:
                break
            all_tags.extend(batch)
            if len(batch) < 200:
                break
            page += 1
        return all_tags
