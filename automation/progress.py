from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProgressPresentation:
    step: str
    message: str
    level: str = "info"
    checkpoint: bool = False


def format_progress_step(
    scenario_type: str,
    step: str,
    *,
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> ProgressPresentation | None:
    """Convert noisy scenario debug steps into short user-facing milestones."""
    normalized = (step or "").lower()
    data = data or {}

    common = _format_common_step(normalized, scenario_type)
    if common:
        return common

    if scenario_type == "register_mexc":
        return _format_register_step(normalized, data, level)
    if scenario_type == "link_mexc_2fa":
        return _format_2fa_step(normalized, data, level)
    if scenario_type == "create_mexc_api":
        return _format_api_step(normalized, data, level)
    if scenario_type == "open_mexc":
        return _format_open_mexc_step(normalized)
    return None


def _format_common_step(step: str, scenario_type: str) -> ProgressPresentation | None:
    if step == "execute_start":
        return ProgressPresentation("started", _scenario_title(scenario_type, "started"), checkpoint=True)
    if step == "browser_start_requested":
        return ProgressPresentation("browser_opening", "Opening AdsPower browser...", checkpoint=True)
    if step == "browser_started":
        return ProgressPresentation("browser_ready", "AdsPower browser is ready.", checkpoint=True)
    if step == "browser_stopped":
        return ProgressPresentation("browser_stopped", "Browser session stopped.")
    return None


def _format_open_mexc_step(step: str) -> ProgressPresentation | None:
    mapping = {
        "open_mexc_navigate_start": ProgressPresentation("mexc_loading", "Loading MEXC...", checkpoint=True),
        "open_mexc_page_loaded": ProgressPresentation("mexc_loaded", "MEXC page loaded.", checkpoint=True),
        "open_mexc_screenshot_taken": ProgressPresentation("mexc_ready", "MEXC profile opened.", "success", True),
    }
    return mapping.get(step)


def _format_register_step(
    step: str,
    data: dict[str, Any],
    level: str,
) -> ProgressPresentation | None:
    checkpoint = str(data.get("checkpoint") or "")
    if step == "checkpoint_wait_for_page":
        return ProgressPresentation("page_loading", "Page is loading. Waiting for a known screen...", "warning", True)
    if step == "checkpoint_wait_resolved":
        return ProgressPresentation("screen_detected", "Known screen detected.", "success", True)
    if step == "checkpoint_network_state_detected":
        return ProgressPresentation("network_attention", "Page is still loading or connection is unstable.", "warning", True)
    if step == "checkpoint_manual_assist_required":
        return ProgressPresentation("manual_control", "Manual control is needed. Use the browser; I will keep watching.", "warning", True)
    if step == "checkpoint_manual_assist_resume":
        return ProgressPresentation("ready_to_resume", "Known screen detected. Ready to continue.", "success", True)
    if step == "checkpoint_captcha_detected":
        return ProgressPresentation("captcha_required", "CAPTCHA required. Solve it in the browser.", "warning", True)
    if step == "checkpoint_captcha_resolved":
        return ProgressPresentation("captcha_solved", "CAPTCHA solved.", "success", True)
    if step == "checkpoint_already_done":
        return ProgressPresentation(
            f"{checkpoint}_done" if checkpoint else "checkpoint_done",
            _checkpoint_done_message(checkpoint),
            "success",
            True,
        )
    if step == "checkpoint_terminal":
        return ProgressPresentation("completed", "MEXC registration completed.", "success", True)
    if step == "manual_assist_required":
        return ProgressPresentation("manual_control", "Manual control is needed. Use the browser; I will keep watching.", "warning", True)
    if step == "manual_assist_resume":
        return ProgressPresentation("ready_to_resume", "Known screen detected. Ready to continue.", "success", True)
    if step == "network_state_detected":
        return ProgressPresentation("network_attention", "Page is still loading or connection is unstable.", "warning", True)
    if step in ("state_registration_already_complete", "success_verification_passed"):
        return ProgressPresentation("completed", "MEXC registration completed.", "success", True)
    if step in ("start",):
        return ProgressPresentation("register_started", "MEXC registration started.", checkpoint=True)
    if step in ("navigate_start",):
        return ProgressPresentation("mexc_loading", "Loading MEXC registration page...", checkpoint=True)
    if step in ("page_loaded",):
        return ProgressPresentation("mexc_loaded", "Registration page loaded.", checkpoint=True)
    if step == "email_filled":
        return ProgressPresentation("email_filled", "Email entered.", checkpoint=True)
    if step == "referral_value_verified":
        return ProgressPresentation("referral_verified", "Referral code accepted.", checkpoint=True)
    if step == "continue_clicked":
        return ProgressPresentation("registration_continue", "Registration form submitted.", checkpoint=True)
    if step == "captcha_detected":
        return ProgressPresentation("captcha_required", "CAPTCHA required. Solve it in the browser.", "warning", True)
    if step == "captcha_solved":
        return ProgressPresentation("captcha_solved", "CAPTCHA solved.", "success", True)
    if step in ("send_code_clicked", "get_code_active_check") and data.get("clicked"):
        return ProgressPresentation("email_code_requested", "Email code requested.", checkpoint=True)
    if step == "email_code_wait_start":
        return ProgressPresentation("email_code_wait", "Waiting for email verification code...", checkpoint=True)
    if step == "email_code_found":
        return ProgressPresentation("email_code_received", "Email code received.", "success", True)
    if step == "verification_code_accepted":
        return ProgressPresentation("email_code_submitted", "Email code accepted.", "success", True)
    if step == "password_filled":
        return ProgressPresentation("password_filled", "Password entered.", checkpoint=True)
    if step == "signup_clicked":
        return ProgressPresentation("registration_submit", "Final registration submitted.", checkpoint=True)
    if step == "success":
        return ProgressPresentation("completed", "MEXC registration completed.", "success", True)
    return _format_warning(step, level)


def _checkpoint_done_message(checkpoint: str) -> str:
    mapping = {
        "navigate": "Registration page is ready.",
        "email": "Email step already completed.",
        "referral": "Referral step already completed.",
        "continue": "Registration form already submitted.",
        "email_code_request": "Email code request step already completed.",
        "email_code_submit": "Email code already accepted.",
        "password": "Password step already completed.",
        "final_submit": "Final registration already submitted.",
    }
    return mapping.get(checkpoint, "Previous step already completed.")


def _format_2fa_step(
    step: str,
    data: dict[str, Any],
    level: str,
) -> ProgressPresentation | None:
    checkpoint = str(data.get("checkpoint") or "")
    if step == "checkpoint_wait_for_page":
        return ProgressPresentation("page_loading", "Page is loading. Waiting for a known screen...", "warning", True)
    if step == "checkpoint_wait_resolved":
        return ProgressPresentation("screen_detected", "Known screen detected.", "success", True)
    if step == "checkpoint_network_state_detected":
        return ProgressPresentation("network_attention", "Page is still loading or connection is unstable.", "warning", True)
    if step == "checkpoint_manual_assist_required":
        return ProgressPresentation("manual_control", "Manual control is needed. Use the browser; I will keep watching.", "warning", True)
    if step == "checkpoint_manual_assist_resume":
        return ProgressPresentation("ready_to_resume", "Known 2FA screen detected. Ready to continue.", "success", True)
    if step == "checkpoint_captcha_detected":
        return ProgressPresentation("captcha_required", "CAPTCHA required. Solve it in the browser.", "warning", True)
    if step == "checkpoint_captcha_resolved":
        return ProgressPresentation("captcha_solved", "CAPTCHA solved.", "success", True)
    if step == "checkpoint_already_done":
        return ProgressPresentation(
            f"{checkpoint}_done" if checkpoint else "checkpoint_done",
            _twofa_checkpoint_done_message(checkpoint),
            "success",
            True,
        )
    if step == "checkpoint_terminal":
        return ProgressPresentation("completed", "MEXC 2FA linked.", "success", True)
    if step == "2fa_start":
        return ProgressPresentation("2fa_started", "MEXC 2FA linking started.", checkpoint=True)
    if step == "2fa_page_loaded":
        return ProgressPresentation("2fa_page_loaded", "Security page loaded.", checkpoint=True)
    if step in ("login_state_wait_for_page", "login_network_state_detected"):
        return ProgressPresentation("login_loading", "MEXC login page is loading.", "warning", True)
    if step == "login_manual_assist_required":
        return ProgressPresentation("manual_control", "Manual control is needed. Use the browser; I will keep watching.", "warning", True)
    if step == "login_manual_assist_resume":
        return ProgressPresentation("ready_to_resume", "Known login screen detected. Ready to continue.", "success", True)
    if step in ("2fa_login_required", "login_email_filled", "login_password_filled", "login_submitted"):
        return ProgressPresentation("login_in_progress", "Logging in to MEXC...", checkpoint=True)
    if step == "2fa_login_completed":
        return ProgressPresentation("login_done", "MEXC login completed.", "success", True)
    if step == "2fa_secret_found":
        return ProgressPresentation("2fa_secret_found", "2FA secret found.", "success", True)
    if step == "2fa_secret_early_save_done":
        return ProgressPresentation("2fa_secret_saved", "2FA secret saved.", "success", True)
    if step == "2fa_secret_reused_from_account":
        return ProgressPresentation("2fa_secret_saved", "Using saved 2FA secret.", "success", True)
    if step == "2fa_get_code_active_check" and data.get("clicked"):
        return ProgressPresentation("email_code_requested", "Email code requested.", checkpoint=True)
    if step == "2fa_email_code_wait_start":
        return ProgressPresentation("email_code_wait", "Waiting for email verification code...", checkpoint=True)
    if step == "2fa_email_code_found":
        return ProgressPresentation("email_code_received", "Email code received.", "success", True)
    if step == "2fa_totp_step_detected":
        return ProgressPresentation("totp_required", "Authenticator code step opened.", checkpoint=True)
    if step == "2fa_totp_input_filled":
        return ProgressPresentation("totp_filled", "Authenticator code entered.", checkpoint=True)
    if step == "2fa_security_verification_submitted":
        return ProgressPresentation("security_submitted", "Security verification submitted.", checkpoint=True)
    if step == "2fa_success":
        return ProgressPresentation("completed", "MEXC 2FA linked.", "success", True)
    if "captcha_detected" in step:
        return ProgressPresentation("captcha_required", "CAPTCHA required. Solve it in the browser.", "warning", True)
    if "captcha_solved" in step:
        return ProgressPresentation("captcha_solved", "CAPTCHA solved.", "success", True)
    return _format_warning(step, level)


def _twofa_checkpoint_done_message(checkpoint: str) -> str:
    mapping = {
        "open_security_page": "Security page is ready.",
        "ensure_login": "MEXC login already completed.",
        "download_authenticator": "Authenticator setup step already opened.",
        "extract_secret": "2FA secret step already completed.",
        "backup_key": "Backup key step already completed.",
        "security_verification": "Security verification already completed.",
        "verify_success": "2FA success already confirmed.",
    }
    return mapping.get(checkpoint, "Previous 2FA step already completed.")


def _format_api_step(
    step: str,
    data: dict[str, Any],
    level: str,
) -> ProgressPresentation | None:
    checkpoint = str(data.get("checkpoint") or "")
    if step == "checkpoint_wait_for_page":
        return ProgressPresentation("page_loading", "Page is loading. Waiting for a known screen...", "warning", True)
    if step == "checkpoint_wait_resolved":
        return ProgressPresentation("screen_detected", "Known API screen detected.", "success", True)
    if step == "checkpoint_network_state_detected":
        return ProgressPresentation("network_attention", "Page is still loading or connection is unstable.", "warning", True)
    if step == "checkpoint_manual_assist_required":
        return ProgressPresentation("manual_control", "Manual control is needed. Use the browser; I will keep watching.", "warning", True)
    if step == "checkpoint_manual_assist_resume":
        return ProgressPresentation("ready_to_resume", "Known API screen detected. Ready to continue.", "success", True)
    if step == "checkpoint_captcha_detected":
        return ProgressPresentation("captcha_required", "CAPTCHA required. Solve it in the browser.", "warning", True)
    if step == "checkpoint_captcha_resolved":
        return ProgressPresentation("captcha_solved", "CAPTCHA solved.", "success", True)
    if step == "checkpoint_already_done":
        return ProgressPresentation(
            f"{checkpoint}_done" if checkpoint else "checkpoint_done",
            _api_checkpoint_done_message(checkpoint),
            "success",
            True,
        )
    if step == "api_create_start":
        return ProgressPresentation("api_started", "MEXC API creation started.", checkpoint=True)
    if step == "api_page_loaded":
        return ProgressPresentation("api_page_loaded", "API page loaded.", checkpoint=True)
    if step in ("login_state_wait_for_page", "login_network_state_detected"):
        return ProgressPresentation("login_loading", "MEXC login page is loading.", "warning", True)
    if step == "login_manual_assist_required":
        return ProgressPresentation("manual_control", "Manual control is needed. Use the browser; I will keep watching.", "warning", True)
    if step == "login_manual_assist_resume":
        return ProgressPresentation("ready_to_resume", "Known login screen detected. Ready to continue.", "success", True)
    if step in ("api_login_required", "login_email_filled", "login_password_filled", "login_submitted"):
        return ProgressPresentation("login_in_progress", "Logging in to MEXC...", checkpoint=True)
    if step == "api_login_completed":
        return ProgressPresentation("login_done", "MEXC login completed.", "success", True)
    if step == "api_form_wait_start":
        return ProgressPresentation("api_form_wait", "Waiting for API form...", checkpoint=True)
    if step == "api_form_wait_done":
        return ProgressPresentation("api_form_ready", "API form is ready.", "success", True)
    if step == "api_permissions_set_done":
        return ProgressPresentation("api_permissions_set", "API permissions configured.", "success", True)
    if step == "api_note_filled":
        return ProgressPresentation("api_note_filled", "API note entered.", checkpoint=True)
    if step == "api_create_clicked":
        return ProgressPresentation("api_create_clicked", "API creation submitted.", checkpoint=True)
    if step == "api_security_verification_start":
        return ProgressPresentation("security_started", "Security verification started.", checkpoint=True)
    if step == "get_code_active_check" and data.get("clicked"):
        return ProgressPresentation("email_code_requested", "Email code requested.", checkpoint=True)
    if step == "email_code_wait_start":
        return ProgressPresentation("email_code_wait", "Waiting for email verification code...", checkpoint=True)
    if step == "email_code_found":
        return ProgressPresentation("email_code_received", "Email code received.", "success", True)
    if step == "api_email_code_filled":
        return ProgressPresentation("email_code_entered", "Email code entered.", checkpoint=True)
    if step == "api_email_totp_combined_modal":
        return ProgressPresentation("security_codes_ready", "Email and authenticator fields are ready.", checkpoint=True)
    if step == "api_totp_code_filled":
        return ProgressPresentation("totp_filled", "Authenticator code entered.", checkpoint=True)
    if step == "api_security_verification_done":
        return ProgressPresentation("security_verified", "Security verification completed.", "success", True)
    if step == "api_key_extract_done":
        return ProgressPresentation("api_keys_found", "API keys extracted.", "success", True)
    if step == "api_confirm_copied_done":
        return ProgressPresentation("api_confirmed", "API key backup confirmed.", checkpoint=True)
    if step == "api_create_success":
        return ProgressPresentation("completed", "MEXC API key created.", "success", True)
    if "captcha_detected" in step:
        return ProgressPresentation("captcha_required", "CAPTCHA required. Solve it in the browser.", "warning", True)
    if "captcha_solved" in step:
        return ProgressPresentation("captcha_solved", "CAPTCHA solved.", "success", True)
    return _format_warning(step, level)


def _api_checkpoint_done_message(checkpoint: str) -> str:
    mapping = {
        "open_api_page": "API page is ready.",
        "ensure_login": "MEXC login already completed.",
        "wait_api_form": "API form is ready.",
        "prepare_api_form": "API form already prepared.",
        "submit_api_create": "API creation already submitted.",
        "security_verification": "Security verification already completed.",
        "extract_api_keys": "API keys already extracted.",
        "confirm_keys_saved": "API key backup already confirmed.",
    }
    return mapping.get(checkpoint, "Previous API step already completed.")


def _format_warning(step: str, level: str) -> ProgressPresentation | None:
    if level != "warning":
        return None
    warning_keywords = ("timeout", "refresh", "retry", "failed", "manual", "network")
    if any(keyword in step for keyword in warning_keywords):
        return ProgressPresentation(step, "Operation needs attention.", "warning")
    return None


def _scenario_title(scenario_type: str, suffix: str) -> str:
    labels = {
        "open_mexc": "Open MEXC",
        "register_mexc": "MEXC registration",
        "link_mexc_2fa": "MEXC 2FA linking",
        "create_mexc_api": "MEXC API creation",
    }
    return f"{labels.get(scenario_type, scenario_type)} {suffix}."
