from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import requests


class MexcApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class MexcDepositRecord:
    amount: Decimal
    coin: str
    network: str
    address: str
    tx_id: str
    insert_time: int
    status: int
    memo: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "MexcDepositRecord":
        return cls(
            amount=Decimal(str(payload.get("amount") or "0")),
            coin=str(payload.get("coin") or ""),
            network=str(payload.get("network") or ""),
            address=str(payload.get("address") or ""),
            tx_id=str(payload.get("txId") or ""),
            insert_time=int(payload.get("insertTime") or 0),
            status=int(payload.get("status") or 0),
            memo=str(payload.get("memo") or payload.get("addressTag") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "coin": self.coin,
            "network": self.network,
            "address": self.address,
            "tx_id": self.tx_id,
            "insert_time": self.insert_time,
            "status": self.status,
            "memo": self.memo,
        }


class MexcApiClient:
    BASE_URL = "https://api.mexc.com"
    SUCCESS_STATUSES = {5, 12}
    MAX_HISTORY_DAYS = 90
    MAX_QUERY_WINDOW_MS = 7 * 24 * 60 * 60 * 1000 - 1000
    MAX_HISTORY_SAFETY_MS = 2 * 60 * 1000

    def __init__(self, api_key: str, secret_key: str, *, base_url: str | None = None):
        self.api_key = api_key.strip()
        self.secret_key = secret_key.strip()
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False

    def latest_successful_deposit(self, *, days: int = MAX_HISTORY_DAYS) -> MexcDepositRecord | None:
        successful = self.successful_deposits(days=days)
        return successful[0] if successful else None

    def successful_deposits(self, *, days: int = MAX_HISTORY_DAYS) -> list[MexcDepositRecord]:
        days = max(1, min(int(days), self.MAX_HISTORY_DAYS))
        end_time = int(time.time() * 1000)
        earliest_time = end_time - days * 24 * 60 * 60 * 1000 + self.MAX_HISTORY_SAFETY_MS
        cursor = end_time
        successful: list[MexcDepositRecord] = []

        while cursor > earliest_time:
            window_start = max(earliest_time, cursor - self.MAX_QUERY_WINDOW_MS)
            deposits = self.get_deposit_history(
                start_time=window_start,
                end_time=cursor,
            )
            successful.extend(item for item in deposits if item.status in self.SUCCESS_STATUSES)
            cursor = window_start - 1
        return sorted(successful, key=lambda item: item.insert_time, reverse=True)

    def get_deposit_history(
        self,
        *,
        start_time: int | None = None,
        end_time: int | None = None,
        coin: str = "",
        status: str = "",
        limit: int = 1000,
    ) -> list[MexcDepositRecord]:
        if start_time is not None and end_time is not None:
            return self._get_deposit_history_range(
                start_time=start_time,
                end_time=end_time,
                coin=coin,
                status=status,
                limit=limit,
            )
        return self._get_deposit_history_window(
            start_time=start_time,
            end_time=end_time,
            coin=coin,
            status=status,
            limit=limit,
        )

    def _get_deposit_history_range(
        self,
        *,
        start_time: int,
        end_time: int,
        coin: str,
        status: str,
        limit: int,
    ) -> list[MexcDepositRecord]:
        if start_time > end_time:
            return []
        records: list[MexcDepositRecord] = []
        cursor = int(start_time)
        final_end = int(end_time)
        while cursor <= final_end:
            window_end = min(final_end, cursor + self.MAX_QUERY_WINDOW_MS)
            records.extend(
                self._get_deposit_history_window(
                    start_time=cursor,
                    end_time=window_end,
                    coin=coin,
                    status=status,
                    limit=limit,
                )
            )
            cursor = window_end + 1
        return records

    def _get_deposit_history_window(
        self,
        *,
        start_time: int | None,
        end_time: int | None,
        coin: str,
        status: str,
        limit: int,
    ) -> list[MexcDepositRecord]:
        params: dict[str, Any] = {
            "coin": coin,
            "status": status,
            "startTime": start_time,
            "endTime": end_time,
            "limit": max(1, min(int(limit), 1000)),
        }
        payload = self._signed_get("/api/v3/capital/deposit/hisrec", params=params)
        if not isinstance(payload, list):
            raise MexcApiError(f"Unexpected MEXC deposit history response: {type(payload).__name__}")
        return [MexcDepositRecord.from_payload(item) for item in payload if isinstance(item, dict)]

    def _signed_get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: int = 15,
    ) -> Any:
        if not self.api_key or not self.secret_key:
            raise MexcApiError("MEXC API key and secret key are required")

        signed_params = self._clean_params(params or {})
        signed_params["recvWindow"] = 5000
        signed_params["timestamp"] = int(time.time() * 1000)
        query = urlencode(signed_params)
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        response = self.session.get(
            url,
            headers={
                "X-MEXC-APIKEY": self.api_key,
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise MexcApiError(f"MEXC API returned non-JSON response: HTTP {response.status_code}") from exc

        if response.status_code >= 400:
            message = self._error_message(payload)
            raise MexcApiError(f"MEXC API error HTTP {response.status_code}: {message}")
        if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
            raise MexcApiError(f"MEXC API error: {self._error_message(payload)}")
        return payload

    @staticmethod
    def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        for key, value in params.items():
            if value is None or value == "":
                continue
            clean[str(key)] = value
        return clean

    @staticmethod
    def _error_message(payload: Any) -> str:
        if isinstance(payload, dict):
            return str(payload.get("msg") or payload.get("message") or payload)
        return str(payload)
