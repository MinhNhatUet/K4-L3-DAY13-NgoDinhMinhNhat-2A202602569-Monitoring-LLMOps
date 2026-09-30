from app.pii import scrub_text
import pytest
from app.logging_config import scrub_event


def test_scrub_cccd() -> None:
    assert scrub_text("CCCD: 079203012345") == "CCCD: [REDACTED_CCCD]"


@pytest.mark.parametrize("card", ["4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111"])
def test_scrub_credit_card(card: str) -> None:
    assert scrub_text(f"Card: {card}") == "Card: [REDACTED_CREDIT_CARD]"


def test_scrub_nested_event_and_exception() -> None:
    event = {
        "session_id": "student@example.com",
        "payload": {"items": [{"cccd": "079203012345"}, "4111 1111 1111 1111"]},
        "exception": "Contact 0901234567",
        "tokens_in": 20,
    }
    safe = scrub_event(None, "error", event)
    assert safe["session_id"] == "[REDACTED_EMAIL]"
    assert safe["payload"]["items"] == [{"cccd": "[REDACTED_CCCD]"}, "[REDACTED_CREDIT_CARD]"]
    assert safe["exception"] == "Contact [REDACTED_PHONE_VN]"
    assert safe["tokens_in"] == 20


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out
