from __future__ import annotations

import re


class PasswordValidator:
    """Validator for current MEXC registration password requirements."""

    MIN_LENGTH = 10
    PATTERN_UPPER = re.compile(r"[A-Z]")
    PATTERN_LOWER = re.compile(r"[a-z]")
    PATTERN_DIGIT = re.compile(r"\d")
    PATTERN_SYMBOL = re.compile(r"[^A-Za-z0-9]")
    PATTERN_ALLOWED = re.compile(r"^[\x21-\x7e]+$")

    @classmethod
    def validate(cls, password: str) -> tuple[bool, str]:
        if len(password) < cls.MIN_LENGTH:
            return False, f"Minimum {cls.MIN_LENGTH} characters"
        if not cls.PATTERN_ALLOWED.match(password):
            return False, "Only English/ASCII characters are allowed"
        if not cls.PATTERN_UPPER.search(password):
            return False, "Add at least 1 uppercase letter (A-Z)"
        if not cls.PATTERN_LOWER.search(password):
            return False, "Add at least 1 lowercase letter (a-z)"
        if not cls.PATTERN_DIGIT.search(password):
            return False, "Add at least 1 number"
        if not cls.PATTERN_SYMBOL.search(password):
            return False, "Add at least 1 symbol"
        return True, ""
