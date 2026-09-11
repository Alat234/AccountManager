from __future__ import annotations

import json
import logging
import os
import threading
import time
import queue
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover - optional runtime dependency
    psutil = None

logger = logging.getLogger(__name__)

LOG_PATH = Path("logs") / "resource_usage.jsonl"
_LOCK = threading.Lock()
_LAST_CPU_TIMES: dict[int, tuple[float, float]] = {}
_CPU_COUNT = os.cpu_count() or 1
_PENDING: queue.Queue = queue.Queue(maxsize=32)
_WORKER_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_LAST_SAMPLE: dict[str, float] = {}


def _sample_worker() -> None:
    while True:
        payload = _PENDING.get()
        try:
            record = build_resource_snapshot(**payload)
            _append_jsonl(record)
            _log_summary(record)
        except Exception:
            logger.debug("Resource monitor snapshot failed", exc_info=True)
        finally:
            _PENDING.task_done()


def emit_resource_event(
    event: str,
    *,
    task_id: str = "",
    scenario: str = "",
    account_email: str = "",
    checkpoint: str = "",
    driver: Any = None,
    fields: dict[str, Any] | None = None,
) -> None:
    """Queue bounded, throttled sampling. The worker never receives WebDriver."""
    global _WORKER
    key = task_id or scenario
    now = time.monotonic()
    terminal = event in {"execute_done", "execute_failed"}
    with _WORKER_LOCK:
        if not terminal and now - _LAST_SAMPLE.get(key, -10) < 5:
            return
        if len(_LAST_SAMPLE) > 256:
            _LAST_SAMPLE.clear()
        _LAST_SAMPLE[key] = now
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_sample_worker, name="resource-sampler", daemon=True)
            _WORKER.start()
        try:
            _PENDING.put_nowait(dict(event=event, task_id=task_id, scenario=scenario,
                account_email=account_email, checkpoint=checkpoint,
                markers=_driver_markers(driver), fields=dict(fields or {})))
        except queue.Full:
            logger.debug("Resource sample dropped: sampler queue full")


def build_resource_snapshot(
    event: str,
    *,
    task_id: str = "",
    scenario: str = "",
    account_email: str = "",
    checkpoint: str = "",
    driver: Any = None,
    fields: dict[str, Any] | None = None,
    markers: dict[str, str] | None = None,
) -> dict[str, Any]:
    markers = dict(markers) if markers is not None else _driver_markers(driver)
    record: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event,
        "task_id": task_id,
        "scenario": scenario,
        "account_email": _mask_email(account_email),
        "checkpoint": checkpoint,
        "fields": fields or {},
        "psutil_available": psutil is not None,
        "driver_markers": markers,
    }
    if psutil is None:
        record["error"] = "psutil is not installed"
        return record

    system = _system_snapshot()
    processes = _related_processes(markers)
    total_rss_mb = round(sum(item.get("rss_mb", 0.0) for item in processes), 2)
    record.update({
        "system": system,
        "process_count": len(processes),
        "total_related_rss_mb": total_rss_mb,
        "processes": processes,
    })
    if processes:
        record["top_process"] = processes[0]
    return record


def _append_jsonl(record: dict[str, Any]) -> None:
    with _LOCK:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size >= 10 * 1024 * 1024:
            for index in (2, 1):
                source = Path(str(LOG_PATH) + f'.{index}')
                if source.exists():
                    source.replace(Path(str(LOG_PATH) + f'.{index + 1}'))
            LOG_PATH.replace(Path(str(LOG_PATH) + '.1'))
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _log_summary(record: dict[str, Any]) -> None:
    top = record.get("top_process") or {}
    logger.info(
        "Resource event=%s task=%s scenario=%s checkpoint=%s processes=%s total_rss_mb=%s top=%s pid=%s role=%s rss_mb=%s cpu_percent=%s",
        record.get("event"),
        record.get("task_id") or "-",
        record.get("scenario") or "-",
        record.get("checkpoint") or "-",
        record.get("process_count", 0),
        record.get("total_related_rss_mb", 0),
        top.get("name", "-"),
        top.get("pid", "-"),
        top.get("role", "-"),
        top.get("rss_mb", "-"),
        top.get("cpu_percent", "-"),
    )


def _system_snapshot() -> dict[str, Any]:
    try:
        memory = psutil.virtual_memory()
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_total_mb": round(memory.total / 1024 / 1024, 2),
            "memory_used_mb": round(memory.used / 1024 / 1024, 2),
            "memory_available_mb": round(memory.available / 1024 / 1024, 2),
            "memory_percent": memory.percent,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _driver_markers(driver: Any) -> dict[str, str]:
    if driver is None:
        return {}
    markers: dict[str, str] = {}
    for attr, key in (
        ("_adspower_profile_id", "profile_id"),
        ("_adspower_debug_port", "debug_port"),
        ("_adspower_selenium_address", "selenium_address"),
        ("_adspower_webdriver_path", "webdriver_path"),
        ("_chromedriver_pid", "chromedriver_pid"),
    ):
        value = str(getattr(driver, attr, "") or "").strip()
        if value:
            markers[key] = value
    if "selenium_address" in markers:
        port = markers["selenium_address"].rsplit(":", 1)[-1].strip()
        if port.isdigit():
            markers["selenium_port"] = port
    return markers


def _related_processes(markers: dict[str, str]) -> list[dict[str, Any]]:
    current = psutil.Process()
    related: dict[int, list[str]] = {current.pid: ["app_process"]}

    for child in _safe_children(current):
        related.setdefault(child.pid, []).append("app_child")

    chromedriver_pid = markers.get("chromedriver_pid", "")
    if chromedriver_pid.isdigit():
        related.setdefault(int(chromedriver_pid), []).append("chromedriver_pid")

    root_matches: list[Any] = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "exe", "cmdline", "create_time"]):
        reasons = _process_match_reasons(proc, markers)
        if not reasons:
            continue
        related.setdefault(proc.pid, []).extend(reasons)
        if _is_browser_process(proc):
            root_matches.append(proc)

    for root in root_matches:
        for child in _safe_children(root):
            related.setdefault(child.pid, []).append(f"child_of:{root.pid}")

    processes: list[dict[str, Any]] = []
    for pid, reasons in related.items():
        try:
            proc = psutil.Process(pid)
        except Exception:
            continue
        info = _process_info(proc, sorted(set(reasons)))
        if info:
            processes.append(info)

    processes.sort(key=lambda item: item.get("rss_mb", 0.0), reverse=True)
    return processes


def _process_match_reasons(proc: Any, markers: dict[str, str]) -> list[str]:
    try:
        cmdline = " ".join(proc.info.get("cmdline") or proc.cmdline() or [])
        exe = str(proc.info.get("exe") or proc.exe() or "")
        name = str(proc.info.get("name") or proc.name() or "")
    except Exception:
        return []
    haystack = f"{name} {exe} {cmdline}".lower()
    reasons: list[str] = []

    debug_port = markers.get("debug_port", "")
    if debug_port and (
        f"remote-debugging-port={debug_port}" in haystack
        or f":{debug_port}" in haystack
        or f"={debug_port}" in haystack
    ):
        reasons.append("adspower_debug_port")

    selenium_port = markers.get("selenium_port", "")
    if selenium_port and (f":{selenium_port}" in haystack or f"={selenium_port}" in haystack):
        reasons.append("selenium_port")

    profile_id = markers.get("profile_id", "").lower()
    if profile_id and profile_id in haystack:
        reasons.append("adspower_profile_id")

    webdriver_path = markers.get("webdriver_path", "").lower()
    if webdriver_path and webdriver_path in haystack:
        reasons.append("webdriver_path")

    return reasons


def _process_info(proc: Any, reasons: list[str]) -> dict[str, Any] | None:
    try:
        with proc.oneshot():
            memory = proc.memory_info()
            full_memory = _safe_memory_full_info(proc)
            cpu_times = proc.cpu_times()
            cpu_seconds = float(cpu_times.user + cpu_times.system)
            now = time.time()
            cpu_percent = _cpu_percent_since_last(proc.pid, now, cpu_seconds)
            cmdline = proc.cmdline()
            info = {
                "pid": proc.pid,
                "ppid": proc.ppid(),
                "name": proc.name(),
                "role": _process_role(proc, reasons),
                "matched_by": reasons,
                "status": proc.status(),
                "create_time": datetime.fromtimestamp(proc.create_time()).isoformat(timespec="seconds"),
                "rss_mb": round(memory.rss / 1024 / 1024, 2),
                "vms_mb": round(memory.vms / 1024 / 1024, 2),
                "uss_mb": round(getattr(full_memory, "uss", 0) / 1024 / 1024, 2) if full_memory else None,
                "cpu_percent": cpu_percent,
                "cpu_time_seconds": round(cpu_seconds, 2),
                "thread_count": proc.num_threads(),
                "exe": _shorten(proc.exe(), 260),
                "cmdline": _shorten(" ".join(cmdline), 800),
            }
            return info
    except Exception:
        logger.debug("Could not collect process info pid=%s", getattr(proc, "pid", "?"), exc_info=True)
        return None


def _cpu_percent_since_last(pid: int, now: float, cpu_seconds: float) -> float | None:
    previous = _LAST_CPU_TIMES.get(pid)
    _LAST_CPU_TIMES[pid] = (now, cpu_seconds)
    if previous is None:
        return None
    previous_time, previous_cpu = previous
    elapsed = max(now - previous_time, 0.001)
    cpu_delta = max(cpu_seconds - previous_cpu, 0.0)
    return round((cpu_delta / elapsed / _CPU_COUNT) * 100, 2)


def _safe_children(proc: Any) -> list[Any]:
    try:
        return proc.children(recursive=True)
    except Exception:
        return []


def _safe_memory_full_info(proc: Any) -> Any:
    try:
        return proc.memory_full_info()
    except Exception:
        return None


def _is_browser_process(proc: Any) -> bool:
    try:
        name = str(proc.info.get("name") or proc.name() or "").lower()
    except Exception:
        return False
    return any(fragment in name for fragment in ("chrome", "chromedriver", "adspower"))


def _process_role(proc: Any, reasons: list[str]) -> str:
    name = ""
    try:
        name = proc.name().lower()
    except Exception:
        pass
    if "app_process" in reasons:
        return "app_python"
    if "chromedriver_pid" in reasons or "chromedriver" in name:
        return "chromedriver"
    if "adspower_debug_port" in reasons and "chrome" in name:
        return "adspower_chrome_root"
    if any(reason.startswith("child_of:") for reason in reasons) and "chrome" in name:
        return "adspower_chrome_child"
    if "adspower" in name:
        return "adspower"
    if "chrome" in name:
        return "chrome"
    if "app_child" in reasons:
        return "app_child"
    return "process"


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = f"{name[:1]}***"
    else:
        masked = f"{name[0]}***{name[-1]}"
    return f"{masked}@{domain}"


def _shorten(value: str, limit: int) -> str:
    value = value or ""
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."
