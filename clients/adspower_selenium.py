from __future__ import annotations

import logging

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

from clients.adspower import AdsPowerClient

logger = logging.getLogger(__name__)


def open_adspower_selenium_driver(
    adspower: AdsPowerClient,
    profile_id: str,
    *,
    context: str,
) -> webdriver.Chrome:
    logger.info(
        "AdsPower Selenium attach start context=%s profile_id=%s",
        context,
        profile_id,
    )
    conn = adspower.start_browser(profile_id)
    if not conn:
        raise RuntimeError("Failed to start AdsPower browser")
    if not conn.selenium_address or not conn.webdriver_path:
        logger.error(
            "AdsPower returned incomplete Selenium data context=%s profile_id=%s selenium=%s webdriver_path=%s debug_port=%s",
            context,
            profile_id,
            conn.selenium_address,
            conn.webdriver_path,
            conn.debug_port,
        )
        raise RuntimeError("AdsPower did not return Selenium connection data")

    logger.info(
        "AdsPower Selenium connection data context=%s profile_id=%s selenium=%s webdriver_path=%s debug_port=%s",
        context,
        profile_id,
        conn.selenium_address,
        conn.webdriver_path,
        conn.debug_port,
    )
    options = Options()
    options.add_experimental_option("debuggerAddress", conn.selenium_address)
    service = Service(conn.webdriver_path)

    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception:
        logger.exception(
            "Selenium attach failed context=%s profile_id=%s selenium=%s webdriver_path=%s",
            context,
            profile_id,
            conn.selenium_address,
            conn.webdriver_path,
        )
        raise

    logger.info(
        "Selenium attached context=%s profile_id=%s session_id=%s",
        context,
        profile_id,
        getattr(driver, "session_id", ""),
    )
    return driver
