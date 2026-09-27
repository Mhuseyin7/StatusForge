import asyncio
import ipaddress
import json
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import dns.resolver
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
        if monitor.type == MonitorType.JSON and not json_assertions(response, config.get("assertions", [])):
            return CheckResult(MonitorStatus.DOWN, elapsed, response.status_code, "JSON_ASSERTION_FAILED", "One or more JSON assertions failed")
        return CheckResult(MonitorStatus.UP, elapsed, response.status_code, metadata={"payload_bytes": len(response.content), "redirects": redirects})
    except UnsafeTargetError as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="UNSAFE_TARGET", error_message=str(exc))
    except httpx.TimeoutException:
        return CheckResult(MonitorStatus.DOWN, None, error_code="TIMEOUT", error_message="Request timed out")
    except httpx.HTTPError as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="NETWORK_ERROR", error_message=str(exc)[:500])


def json_assertions(response: httpx.Response, assertions: list[dict]) -> bool:
    if not assertions:
        return True
    try:
        data = response.json()
    except json.JSONDecodeError:
        return False
    for assertion in assertions:
        value = data
        for key in str(assertion.get("path", "")).strip("$.").split("."):
            if not key or not isinstance(value, dict) or key not in value:
                return False
            value = value[key]
        operator = assertion.get("operator", "equals")
        expected = assertion.get("value")
        if operator == "exists" and value is None:
            return False
        if operator == "equals" and value != expected:
            return False
        if operator == "min" and (not isinstance(value, (int, float)) or value < expected):
            return False
        if operator == "max" and (not isinstance(value, (int, float)) or value > expected):
            return False
    return True


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
    except (TimeoutError, OSError, ValueError, UnsafeTargetError) as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="TCP_ERROR", error_message=str(exc)[:500])


async def dns_check(monitor: Monitor) -> CheckResult:
    host = str(monitor.config.get("hostname", ""))
    record_type = str(monitor.config.get("record_type", "A")).upper()
    started = time.perf_counter()
    try:
        safe_hostname(host)
        records = await asyncio.to_thread(dns.resolver.resolve, host, record_type, lifetime=monitor.timeout_seconds)
        values = sorted(str(record).rstrip(".") for record in records)
        expected = monitor.config.get("expected_values", [])
        if expected and not set(expected).issubset(values):
            return CheckResult(MonitorStatus.DOWN, round((time.perf_counter() - started) * 1000), error_code="DNS_VALUE_MISMATCH", error_message="Expected DNS records were not returned", metadata={"records": values})
        return CheckResult(MonitorStatus.UP, round((time.perf_counter() - started) * 1000), metadata={"records": values})
    except (dns.exception.DNSException, UnsafeTargetError, ValueError) as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="DNS_ERROR", error_message=str(exc)[:500])


def certificate_info(host: str, port: int, timeout: int) -> dict:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as connection, context.wrap_socket(connection, server_hostname=host) as tls:
        return tls.getpeercert()


async def ssl_check(monitor: Monitor) -> CheckResult:
    host = str(monitor.config.get("host", ""))
    port = int(monitor.config.get("port", 443))
    started = time.perf_counter()
    try:
        resolve_public(host)
        certificate = await asyncio.wait_for(asyncio.to_thread(certificate_info, host, port, monitor.timeout_seconds), timeout=monitor.timeout_seconds + 1)
        expires = ssl.cert_time_to_seconds(certificate["notAfter"])
        days_remaining = max(0, round((expires - time.time()) / 86400))
        status = MonitorStatus.DEGRADED if days_remaining <= int(monitor.config.get("warning_days", 14)) else MonitorStatus.UP
        return CheckResult(status, round((time.perf_counter() - started) * 1000), metadata={"issuer": certificate.get("issuer", []), "subject": certificate.get("subject", []), "expires_at": expires, "days_remaining": days_remaining})
    except (OSError, ssl.SSLError, TimeoutError, UnsafeTargetError, ValueError) as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="TLS_ERROR", error_message=str(exc)[:500])


async def domain_check(monitor: Monitor) -> CheckResult:
    domain = str(monitor.config.get("domain", "")).lower().strip()
    if not domain or "/" in domain:
        return CheckResult(MonitorStatus.DOWN, None, error_code="INVALID_DOMAIN", error_message="A valid domain is required")
    try:
        async with httpx.AsyncClient(timeout=monitor.timeout_seconds) as client:
            response = await client.get(f"https://rdap.org/domain/{domain}")
        if response.status_code != 200:
            return CheckResult(MonitorStatus.DOWN, None, response.status_code, "RDAP_ERROR", "RDAP lookup failed")
        events = response.json().get("events", [])
        expiry = next((event.get("eventDate") for event in events if event.get("eventAction") == "expiration"), None)
        return CheckResult(MonitorStatus.UP if expiry else MonitorStatus.UNKNOWN, None, response.status_code, metadata={"expiration_date": expiry})
    except httpx.HTTPError as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="RDAP_ERROR", error_message=str(exc)[:500])


async def ping_check(monitor: Monitor) -> CheckResult:
    host = str(monitor.config.get("host", ""))
    try:
        resolve_public(host)
        started = time.perf_counter()
        process = await asyncio.create_subprocess_exec("ping", "-c", "1", "-W", str(monitor.timeout_seconds), host, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(process.wait(), timeout=monitor.timeout_seconds + 1)
        if process.returncode == 0:
            return CheckResult(MonitorStatus.UP, round((time.perf_counter() - started) * 1000))
        return CheckResult(MonitorStatus.DOWN, None, error_code="PING_FAILED", error_message="Host did not respond to ICMP")
    except (OSError, TimeoutError, UnsafeTargetError) as exc:
        return CheckResult(MonitorStatus.DOWN, None, error_code="PING_ERROR", error_message=str(exc)[:500])


async def execute(monitor: Monitor) -> CheckResult:
    if monitor.type in {MonitorType.HTTP, MonitorType.KEYWORD, MonitorType.JSON}:
        return await http_check(monitor)
    if monitor.type == MonitorType.TCP:
        return await tcp_check(monitor)
    if monitor.type == MonitorType.DNS:
        return await dns_check(monitor)
    if monitor.type == MonitorType.SSL:
        return await ssl_check(monitor)
    if monitor.type == MonitorType.DOMAIN:
        return await domain_check(monitor)
    if monitor.type == MonitorType.PING:
        return await ping_check(monitor)
    return CheckResult(MonitorStatus.UNKNOWN, None, error_code="UNSUPPORTED_MONITOR", error_message=f"{monitor.type.value} execution is not configured")
