"""Guard against entering real personal data (hackathon rule: no real names, NID numbers, phone numbers or addresses).
Names cannot be detected reliably, so the UI also tells users to use placeholder labels."""
import re

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def personal_data_reason(text) -> str:
    """Return a reason string if the text looks like an NID / phone number / email, else ''."""
    s = str(text or "")
    if _EMAIL.search(s):
        return "looks like an email address"
    digits = re.sub(r"[\s\-().]", "", s)
    if re.search(r"\+?880\d{9,10}", digits) or re.search(r"(?<!\d)01[3-9]\d{8}(?!\d)", digits):
        return "looks like a phone number"
    if re.search(r"\d{10,}", digits):
        return "contains a long number (like an NID or phone number)"
    return ""
