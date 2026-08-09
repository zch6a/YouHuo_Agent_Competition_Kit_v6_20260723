from __future__ import annotations

import pytest

from youhuo.privacy import redact_payload, redact_text
from youhuo.v5_services import PrivacyRedactor


@pytest.mark.parametrize("phone", ["138 1234 5678", "138-1234-5678", "13812345678"])
def test_formatted_mobile_numbers_are_redacted_in_both_privacy_layers(phone: str) -> None:
    assert "138" not in redact_text(phone)
    assert "138" not in PrivacyRedactor.redact_text(phone)


@pytest.mark.parametrize(
    "key",
    ["access_token", "ACCESS-TOKEN", "refresh_token", "api_key", "client_secret", "identity_token"],
)
def test_structured_secret_keys_are_hidden_recursively(key: str) -> None:
    payload = {"outer": {key: "super-secret-value"}}
    redacted = redact_payload(payload)
    assert redacted["outer"][key] == "[已隐藏]"
    legacy = PrivacyRedactor.redact_value(payload)
    assert legacy["outer"][key] == "[已隐藏]"


def test_spaced_verification_code_is_redacted_when_context_marks_it_as_code() -> None:
    value = redact_text("短信验证码 12 34 56，请不要告诉别人")
    assert "12 34 56" not in value
    assert "验证码已脱敏" in value
