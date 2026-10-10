import pytest
from fastapi import HTTPException
from httpx import Response

from app.models import MonitorType
from app.routers.monitors import validate_monitor_configuration
from app.services.monitoring import UnsafeTargetError, json_assertions, safe_hostname


def test_localhost_is_rejected() -> None:
    with pytest.raises(UnsafeTargetError):
        safe_hostname("localhost")


def test_metadata_target_is_rejected() -> None:
    with pytest.raises(UnsafeTargetError):
        safe_hostname("metadata.google.internal")


def test_json_assertions_support_nested_values_and_limits() -> None:
    response = Response(200, json={"service": {"healthy": True, "latency": 42}})

    assert json_assertions(
        response,
        [
            {"path": "$.service.healthy", "operator": "equals", "value": True},
            {"path": "$.service.latency", "operator": "max", "value": 50},
            {"path": "$.service", "operator": "exists"},
        ],
    )


def test_json_assertions_fail_for_missing_or_unmatched_data() -> None:
    response = Response(200, json={"service": {"latency": 42}})

    assert not json_assertions(response, [{"path": "$.service.latency", "operator": "min", "value": 100}])
    assert not json_assertions(response, [{"path": "$.service.region", "operator": "exists"}])


def test_monitor_configuration_requires_type_specific_fields() -> None:
    with pytest.raises(HTTPException, match="TCP monitors require config.host"):
        validate_monitor_configuration(MonitorType.TCP, {})


def test_monitor_configuration_rejects_unsafe_http_target() -> None:
    with pytest.raises(HTTPException, match="local and metadata targets are blocked"):
        validate_monitor_configuration(MonitorType.HTTP, {"url": "http://localhost:8000"})
