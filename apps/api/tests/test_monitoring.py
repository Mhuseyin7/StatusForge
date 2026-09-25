import pytest

from app.services.monitoring import UnsafeTargetError, safe_hostname


def test_localhost_is_rejected() -> None:
    with pytest.raises(UnsafeTargetError):
        safe_hostname("localhost")


def test_metadata_target_is_rejected() -> None:
    with pytest.raises(UnsafeTargetError):
        safe_hostname("metadata.google.internal")
