import pytest

from scripts.check_real_operations import validate_denial, validate_pin


def test_missing_client_or_dns_error_cannot_masquerade_as_network_denial():
    for control, code, text in [(1, 1, "timed out"), (0, 0, "timed out"),
                                (0, 127, "wget: not found"), (0, 1, "bad address")]:
        with pytest.raises(ValueError):
            validate_denial(control, code, text)
    validate_denial(0, 1, "wget: download timed out")


def test_dependency_outage_cannot_masquerade_as_pin_mismatch():
    with pytest.raises(ValueError):
        validate_pin({"live": 200, "ready": 503, "checks": {"chroma": "unavailable"}})
    validate_pin({"live": 200, "ready": 503,
                  "checks": {"embedding_pin": "mismatch: API model=wrong"}})
