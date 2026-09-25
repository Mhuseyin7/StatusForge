import asyncio
import ipaddress
import socket
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.models import Monitor, MonitorStatus, MonitorType


class UnsafeTargetError(ValueError):
    pass


@dataclass(frozen=True)
class CheckResult:
    status: MonitorStatus
    response_time_ms: int | None
    status_code: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict | None = None


def safe_hostname(hostname: str) -> None:
    normalized = hostname.strip().lower().rstrip(".")
    if normalized in {"localhost", "metadata.google.internal", "metadata.azure.com"} or normalized.endswith(".localhost"):
        raise UnsafeTargetError("local and metadata targets are blocked")


def resolve_public(hostname: str) -> list[str]:
    safe_hostname(hostname)
    try:
        values = {info[4][0] for info in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnsafeTargetError("hostname could not be resolved") from exc
    if not values:
        raise UnsafeTargetError("hostname has no address records")
    if not get_settings().allow_private_monitors:
        for value in values:
            ip = ipaddress.ip_address(value)
            if not ip.is_global:
                raise UnsafeTargetError("private, loopback, or reserved targets are blocked")
    return list(values)


def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeTargetError("only absolute HTTP(S) URLs without credentials are allowed")
    resolve_public(parsed.hostname)


async def http_check(monitor: Monitor) -> CheckResult:
    config = monitor.config
    url = str(config["url"])
    timeout = httpx.Timeout(monitor.timeout_seconds)
    try:
        validate_url(url)
        started = time.perf_counter()
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers={"User-Agent": "StatusForge/0.1"}) as client:
            response = await client.request(config.get("method", "GET"), url, headers=config.get("headers", {}), content=config.get("body"))
            redirects = 0
            while response.is_redirect and config.get("follow_redirects", True) and redirects < 5:
                location = response.headers.get("location")
                if not location:
                    break
                redirect_url = str(response.url.join(location))
                validate_url(redirect_url)
                response = await client.get(redirect_url)
                redirects += 1
        elapsed = round((time.perf_counter() - started) * 1000)
        expected = config.get("expected_status_codes", [200, 201, 202, 204])
        if response.status_code not in expected:
            return CheckResult(MonitorStatus.DOWN, elapsed, response.status_code, "UNEXPECTED_STATUS", f"Expected {expected}, got {response.status_code}")
        body = response.text[:1_000_000]
        expected_keyword = config.get("expected_keyword")
        forbidden_keyword = config.get("forbidden_keyword")
        if expected_keyword and expected_keyword not in body:
            return CheckResult(MonitorStatus.DOWN, elapsed, response.status_code, "KEYWORD_MISSING", "Expected keyword was not found")
        if forbidden_keyword and forbidden_keyword in body:
            return CheckResult(MonitorStatus.DOWN, elapsed, response.status_code, "KEYWORD_PRESENT", "Forbidden keyword was found")
        return CheckResult(MonitorStatus.UP, elapsed, response.status_code, metadata={"payload_bytes": len(response.content), "redirects": redirects})
    except UnsafeTargetError as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="UNSAFE_TARGET", error_message=str(exc))
    except httpx.TimeoutException:
        return CheckResult(MonitorStatus.DOWN, None, error_code="TIMEOUT", error_message="Request timed out")
    except httpx.HTTPError as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="NETWORK_ERROR", error_message=str(exc)[:500])


async def tcp_check(monitor: Monitor) -> CheckResult:
    host = str(monitor.config.get("host", ""))
    port = int(monitor.config.get("port", 0))
    started = time.perf_counter()
    try:
        resolve_public(host)
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=monitor.timeout_seconds)
        writer.close()
        await writer.wait_closed()
        return CheckResult(MonitorStatus.UP, round((time.perf_counter() - started) * 1000))
    except (OSError, ValueError, asyncio.TimeoutError, UnsafeTargetError) as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="TCP_ERROR", error_message=str(exc)[:500])


async def execute(monitor: Monitor) -> CheckResult:
    if monitor.type in {MonitorType.HTTP, MonitorType.KEYWORD, MonitorType.JSON}:
        return await http_check(monitor)
    if monitor.type == MonitorType.TCP:
        return await tcp_check(monitor)
    return CheckResult(MonitorStatus.UNKNOWN, None, error_code="UNSUPPORTED_MONITOR", error_message=f"{monitor.type.value} execution is not configured")
