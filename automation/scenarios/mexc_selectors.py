from __future__ import annotations

from dataclasses import dataclass

from selenium.webdriver.common.by import By

Locator = tuple[str, str]


@dataclass(frozen=True)
class MexcRegistrationSelectors:
    email_input: tuple[Locator, ...] = (
        (By.ID, "mx_sign_account_mixed_input"),
        (By.CSS_SELECTOR, "input#mx_sign_account_mixed_input"),
        (By.CSS_SELECTOR, "input[placeholder*='email']"),
        (By.CSS_SELECTOR, "input[placeholder*='Email']"),
        (By.CSS_SELECTOR, "input[placeholder*='phone']"),
        (By.CSS_SELECTOR, "input[type='email']"),
        (By.CSS_SELECTOR, "input[name*='email']"),
        (By.CSS_SELECTOR, "input[id*='email']"),
        (By.CSS_SELECTOR, "input[autocomplete='email']"),
        (By.CSS_SELECTOR, "input.ant-input.ant-input-lg[type='text']"),
    )
    referral_toggle: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, "label[for='full-sign-up-account-form_inviteCode']"),
        (By.CSS_SELECTOR, "span[class*='inviteCodeToggle']"),
        (By.CSS_SELECTOR, "span[class*='inviteCodeCheckLabel']"),
        (By.CSS_SELECTOR, "svg[class*='inviteCodeExpandArrow']"),
        (By.XPATH, "//label[@for='full-sign-up-account-form_inviteCode']"),
        (By.XPATH, "//span[contains(normalize-space(.), 'Referral Code')]"),
        (By.XPATH, "//span[contains(normalize-space(.), 'Invitation code')]"),
    )
    referral_input: tuple[Locator, ...] = (
        (By.ID, "full-sign-up-account-form_inviteCode"),
        (By.CSS_SELECTOR, "input#full-sign-up-account-form_inviteCode"),
        (By.CSS_SELECTOR, "input[name*='invite']"),
        (By.CSS_SELECTOR, "input[name*='referral']"),
        (By.CSS_SELECTOR, "input[id*='invite']"),
        (By.CSS_SELECTOR, "input[id*='referral']"),
        (By.CSS_SELECTOR, "input[placeholder*='invitation']"),
        (By.CSS_SELECTOR, "input[placeholder*='Invitation']"),
        (By.CSS_SELECTOR, "input[placeholder*='invite']"),
        (By.CSS_SELECTOR, "input[placeholder*='referral']"),
    )
    continue_button: tuple[Locator, ...] = (
        (By.XPATH, "//button[@type='submit'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue')]"),
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue')]"),
        (By.CSS_SELECTOR, "button[type='submit']"),
    )
    send_code_button: tuple[Locator, ...] = (
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'get code')]"),
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send code')]"),
        (By.XPATH, "//*[self::button or self::span or @role='button'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'get code')]"),
        (By.XPATH, "//*[self::button or self::span or @role='button'][contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'send code')]"),
        (By.CSS_SELECTOR, "button[class*='code'], button[class*='send']"),
        (By.CSS_SELECTOR, "[class*='captchaSend'] span, [class*='textButton']"),
    )
    verification_code_input: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, ".react-code-input input[type='number']"),
        (By.CSS_SELECTOR, "[class*='auth_code_input'] input[type='number']"),
        (By.CSS_SELECTOR, "[class*='sign_up_auth_code_input'] input[type='number']"),
        (By.CSS_SELECTOR, "input[data-id][type='number']"),
        (By.CSS_SELECTOR, "input[maxlength='1'][type='number']"),
        (By.CSS_SELECTOR, "input[maxlength='6'][type='number']"),
        (By.CSS_SELECTOR, "input[name*='code']"),
        (By.CSS_SELECTOR, "input[id*='code']"),
        (By.CSS_SELECTOR, "input[placeholder*='code']"),
        (By.CSS_SELECTOR, "input[placeholder*='Code']"),
        (By.CSS_SELECTOR, "input[autocomplete='one-time-code']"),
    )
    password_input: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, "input[type='password']"),
        (By.CSS_SELECTOR, "input[name*='password']"),
        (By.CSS_SELECTOR, "input[id*='password']"),
        (By.CSS_SELECTOR, "input[placeholder*='password']"),
        (By.CSS_SELECTOR, "input[placeholder*='Password']"),
    )
    agree_checkbox: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, "input[type='checkbox']"),
        (By.CSS_SELECTOR, "[role='checkbox']"),
        (By.CSS_SELECTOR, "[class*='checkbox'], [class*='agree']"),
    )
    signup_button: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign up')]"),
        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'register')]"),
    )
    error_message: tuple[Locator, ...] = (
        (By.CSS_SELECTOR, "[class*='error']"),
        (By.CSS_SELECTOR, "[class*='invalid']"),
        (By.CSS_SELECTOR, "[role='alert']"),
    )
