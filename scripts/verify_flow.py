"""One explicit functional smoke against the frozen v1.3.0-rc.1 public API.

Requires all migrations (including Carrier reference data), running workers, and
the selected CARRIER_*_WEBHOOK_SECRET in the environment. Creates one synthetic
Order/Shipment, sends one delivery event, observes completion, then sends exactly
one intentional duplicate. It never retries mutations or repairs blocked work.
No application imports, external packages, cloud commands, or benchmark traffic.
The recorded expected SHA identifies the reference contract, not the deployed
runtime; this verifier has no endpoint that verifies application image identity.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import os
import queue
import ssl
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, Protocol
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

EXPECTED_APPLICATION_SHA = "9e3a135a00db218643633c7165d3106f0c8285e1"
MAX_RESPONSE_BYTES = 65_536
SECRET_ENV = {
    "carrier-alpha": "CARRIER_ALPHA_WEBHOOK_SECRET",
    "carrier-beta": "CARRIER_BETA_WEBHOOK_SECRET",
}


class Failure(Exception):
    """Only locally defined, value-free diagnostics may cross this boundary."""

    def __init__(self, code: str, exit_code: int = 4) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


def require(condition: bool, code: str = "SCHEMA_UNEXPECTED") -> None:
    if not condition:
        raise Failure(code)


def base_url(value: str) -> str:
    """Permit local tunnels or private IP HTTPS; never arbitrary public hosts."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
        host = parsed.hostname
        if not value.isascii() or any(c.isspace() for c in value) or "\\" in value:
            raise ValueError
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError
        address = ipaddress.ip_address("127.0.0.1" if host == "localhost" else host)
        local = address.is_loopback
        private = any(
            address in ipaddress.ip_network(network)
            for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
            if address.version == ipaddress.ip_network(network).version
        )
        if not local and not (private and parsed.scheme == "https"):
            raise ValueError
        return value.rstrip("/")
    except ValueError:
        raise Failure("INVALID_BASE_URL", 2) from None


@dataclass(frozen=True)
class Config:
    base: str
    output_dir: Path
    carrier: str = "carrier-alpha"
    deadline_seconds: float = 60
    request_timeout_seconds: float = 5
    poll_seconds: float = 1
    secret: str = field(default="", repr=False)

    def validate(self) -> None:
        base_url(self.base)
        if self.carrier not in SECRET_ENV or not self.secret:
            raise Failure("MISSING_CARRIER_SECRET_OR_INVALID_CARRIER", 2)
        bounds = (
            (self.deadline_seconds, 1, 300),
            (self.request_timeout_seconds, 0.1, 30),
            (self.poll_seconds, 0.1, 10),
        )
        if any(not math.isfinite(v) or not low <= v <= high for v, low, high in bounds):
            raise Failure("INVALID_TIME_LIMIT", 2)


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes = field(repr=False)


class Transport(Protocol):
    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> Response: ...


class HttpTransport:
    """No proxies, redirects, cookies, retries, or disabled TLS verification.

    The daemon bounds the entire exchange, including slow headers/body, rather
    than relying only on a socket inactivity timeout. A timed-out mutation has an
    unknown outcome; the caller stops and never dispatches another request.
    """

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float
    ) -> Response:
        completed: queue.Queue[Response | Failure] = queue.Queue(maxsize=1)

        def exchange() -> None:
            connection: http.client.HTTPConnection | None = None
            try:
                parsed = urlsplit(url)
                host = "127.0.0.1" if parsed.hostname == "localhost" else parsed.hostname
                if parsed.scheme == "https":
                    connection = http.client.HTTPSConnection(
                        host, parsed.port, timeout=timeout, context=ssl.create_default_context()
                    )
                else:
                    connection = http.client.HTTPConnection(host, parsed.port, timeout=timeout)
                target = parsed.path + ("?" + parsed.query if parsed.query else "")
                connection.request(method, target, body=body, headers=dict(headers))
                response = connection.getresponse()
                # Headers are bounded by http.client; the body has its own strict cap.
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise Failure("RESPONSE_TOO_LARGE")
                pairs = response.getheaders()
                normalized = {key.lower(): value for key, value in pairs}
                for unique in ("location", "content-type"):
                    if sum(key.lower() == unique for key, _ in pairs) > 1:
                        raise Failure("SCHEMA_UNEXPECTED")
                completed.put(Response(response.status, normalized, content))
            except Failure as failure:
                completed.put(failure)
            except (OSError, ValueError, http.client.HTTPException):
                completed.put(Failure("HTTP_TRANSPORT_FAILED", 3))
            finally:
                if connection is not None:
                    connection.close()

        threading.Thread(target=exchange, daemon=True).start()
        try:
            result = completed.get(timeout=timeout)
        except queue.Empty:
            raise Failure("HTTP_TIMEOUT_OUTCOME_UNKNOWN", 3) from None
        if isinstance(result, Failure):
            raise result
        return result


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def signature(secret: str, timestamp: str, event_id: str, raw: bytes) -> str:
    signed = timestamp.encode("ascii") + b"." + event_id.encode("ascii") + b"." + raw
    return "sha256=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def identifier(value: Any) -> str:
    try:
        require(isinstance(value, str))
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise Failure("SCHEMA_UNEXPECTED") from None


def timestamp(value: Any) -> None:
    try:
        require(isinstance(value, str))
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    except (ValueError, TypeError):
        raise Failure("SCHEMA_UNEXPECTED") from None


def json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def invalid_json_constant(value: str) -> NoReturn:
    del value
    raise Failure("SCHEMA_UNEXPECTED")


class Evidence:
    """Exclusive directory/file creation; only caller-selected safe fields persist."""

    def __init__(self, path: Path) -> None:
        try:
            path.mkdir(exist_ok=False)
            self.stream = (path / "observations.jsonl").open("x", encoding="utf-8")
        except OSError:
            raise Failure("OUTPUT_UNAVAILABLE_OR_EXISTS", 2) from None

    def emit(self, phase: str, **fields: object) -> None:
        record = {"observed_at": datetime.now(UTC).isoformat(), "phase": phase, **fields}
        self.stream.write(json.dumps(record, sort_keys=True) + "\n")
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self) -> None:
        self.stream.close()


class Verifier:
    def __init__(
        self,
        config: Config,
        evidence: Evidence,
        transport: Transport,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self.evidence = evidence
        self.transport = transport
        self.monotonic = monotonic
        self.sleep = sleep
        self.now = now
        self.deadline = monotonic() + config.deadline_seconds
        self.run_id = str(uuid4())
        self.event_id = "infra-smoke-" + self.run_id
        self.offered = False
        self.acceptance_observed = False
        self.accepted = False
        self.tracking_completed = False
        self.order_completed = False
        self.notifications_simulated = False
        self.duplicate_verified = False
        self.phase = "prepare"

    def remaining(self) -> float:
        remaining = self.deadline - self.monotonic()
        if remaining <= 0:
            raise Failure("OBSERVATION_DEADLINE", 5)
        return remaining

    def pause(self) -> None:
        self.sleep(min(self.config.poll_seconds, self.remaining()))

    def request(
        self,
        method: str,
        path: str,
        expected: int,
        body: bytes | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[dict[str, Any], Response]:
        timeout = min(self.config.request_timeout_seconds, self.remaining())
        headers = {"Accept": "application/json", "X-Request-ID": str(uuid4())}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        if self.phase == "admission" and method == "POST":
            self.offered = True
            self.evidence.emit("webhook_offered", event_id=self.event_id, unique_events=1)
        elif self.phase == "intentional_duplicate" and method == "POST":
            self.evidence.emit("duplicate_offered", event_id=self.event_id)
        response = self.transport(method, self.config.base + path, headers, body, timeout)
        require(type(response.status) is int)
        self.evidence.emit("http", operation=self.phase, method=method, http_status=response.status)
        if response.status != expected:
            raise Failure("HTTP_STATUS_UNEXPECTED", 3)
        if expected == 202:
            # Record the observed admission before parsing; query failures cannot erase it.
            self.acceptance_observed = True
            self.evidence.emit("acceptance_observed", event_id=self.event_id, http_status=202)
        self.remaining()
        require(len(response.body) <= MAX_RESPONSE_BYTES, "RESPONSE_TOO_LARGE")
        require(
            response.headers.get("content-type", "").split(";")[0].strip() == "application/json"
        )
        try:
            payload = json.loads(
                response.body.decode("utf-8"),
                object_pairs_hook=json_object,
                parse_constant=invalid_json_constant,
            )
        except (ValueError, UnicodeError, RecursionError):
            raise Failure("SCHEMA_UNEXPECTED") from None
        require(isinstance(payload, dict))
        return payload, response

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path, 200)[0]

    def prepare(self) -> tuple[str, str, str]:
        tracking_code = "SMOKE" + self.run_id.replace("-", "").upper()
        payload = {
            "external_reference": "infra-smoke-" + self.run_id,
            "recipient": {
                "name": "Functional Smoke Recipient",
                "email": "functional-smoke@example.test",
                "postal_code": "09700-000",
                "city": "Sao Bernardo do Campo",
                "state": "SP",
            },
        }
        order, _ = self.request("POST", "/api/v1/orders", 201, json_bytes(payload))
        order_id = identifier(order.get("id"))
        require(order.get("status") == "CREATED")
        self.evidence.emit("order_created", order_id=order_id)
        confirmed, _ = self.request("POST", f"/api/v1/orders/{order_id}/confirm", 200)
        require(confirmed.get("id") == order_id and confirmed.get("status") == "CONFIRMED")
        shipment, _ = self.request(
            "POST",
            "/api/v1/shipments",
            201,
            json_bytes(
                {
                    "order_id": order_id,
                    "carrier_code": self.config.carrier,
                    "tracking_code": tracking_code,
                }
            ),
        )
        shipment_id = identifier(shipment.get("id"))
        require(shipment.get("order_id") == order_id and shipment.get("status") == "PENDING")
        require(shipment.get("tracking_code") == tracking_code)
        require(shipment.get("carrier_code") == self.config.carrier)
        self.evidence.emit("shipment_created", order_id=order_id, shipment_id=shipment_id)
        return order_id, shipment_id, tracking_code

    def webhook(self, tracking_code: str) -> tuple[bytes, dict[str, str]]:
        instant = self.now()
        occurred = instant.isoformat()
        signed_at = str(int(instant.timestamp()))
        if self.config.carrier == "carrier-alpha":
            payload = {
                "eventId": self.event_id,
                "trackingCode": tracking_code,
                "status": "DELIVERED",
                "eventDate": occurred,
                "city": "Sao Bernardo do Campo",
                "description": "Synthetic infra smoke",
            }
        else:
            payload = {
                "id": self.event_id,
                "tracking_number": tracking_code,
                "event": {
                    "type": "completed",
                    "occurred_at": occurred,
                    "details": "Synthetic infra smoke",
                },
                "location": {"city": "Sao Bernardo do Campo", "state": "SP"},
            }
        raw = json_bytes(payload)
        return raw, {
            "X-FulfillFlow-Event-Id": self.event_id,
            "X-FulfillFlow-Timestamp": signed_at,
            "X-FulfillFlow-Signature": signature(self.config.secret, signed_at, self.event_id, raw),
        }

    def admit(self, raw: bytes, headers: Mapping[str, str]) -> tuple[str, str]:
        self.phase = "admission"
        accepted, response = self.request(
            "POST", f"/api/v1/carriers/{self.config.carrier}/events", 202, raw, headers
        )
        inbox_id = identifier(accepted.get("inbox_event_id"))
        require(accepted.get("external_event_id") == self.event_id)
        require(accepted.get("status") == "RECEIVED")
        request_id = identifier(accepted.get("request_id"))
        timestamp(accepted.get("received_at"))
        self.accepted = True
        self.evidence.emit(
            "accepted",
            event_id=self.event_id,
            inbox_event_id=inbox_id,
            request_id=request_id,
            received_at=accepted["received_at"],
        )
        expected = f"/api/v1/carrier-events/{inbox_id}"
        location = response.headers.get("location")
        require(isinstance(location, str), "INVALID_LOCATION")
        # Comparing the entire resolved URL also excludes credentials, queries and fragments.
        try:
            require(
                urljoin(self.config.base + "/", location) == self.config.base + expected,
                "INVALID_LOCATION",
            )
        except ValueError:
            raise Failure("INVALID_LOCATION") from None
        return inbox_id, expected

    def tracking(
        self,
        inbox_id: str,
        path: str,
        shipment_id: str,
        *,
        initial_record: dict[str, Any] | None = None,
    ) -> str:
        self.phase = "tracking_observation"
        observed_event_id = None
        while True:
            # Reuse only a response from this observation; later polls always fetch anew.
            record = initial_record if initial_record is not None else self.get(path)
            initial_record = None
            require(
                record.get("id") == inbox_id and record.get("external_event_id") == self.event_id
            )
            require(record.get("carrier_code") == self.config.carrier)
            status, progress = record.get("status"), record.get("progress")
            if progress == "BLOCKED_LOCAL":
                raise Failure("TRACKING_BLOCKED", 6)
            if status == "REJECTED":
                raise Failure("TRACKING_REJECTED", 6)
            if status == "PROCESSED":
                require(progress == "COMPLETED")
                event_id = identifier(record.get("tracking_event_id"))
                require(observed_event_id is None or event_id == observed_event_id)
                result = record.get("result")
                require(isinstance(result, dict))
                require(result.get("kind") == "applied" and result.get("result") == "APPLIED")
                require(
                    result.get("event_id") == event_id and result.get("shipment_id") == shipment_id
                )
                require(
                    result.get("previous_status") == "PENDING"
                    and result.get("current_status") == "DELIVERED"
                )
                timestamp(record.get("completed_at"))
                timestamp(result.get("decided_at"))
                self.tracking_completed = True
                self.evidence.emit(
                    "tracking_completed", tracking_event_id=event_id, result="APPLIED"
                )
                return event_id
            require(status == "RECEIVED" and progress in ("QUEUED", "AWAITING_RESULT"))
            require(record.get("result") is None and record.get("completed_at") is None)
            # The frozen API reads inbox and event separately under READ COMMITTED.
            # An event ID may become visible before this projection reports completion.
            pending_id = record.get("tracking_event_id")
            if pending_id is not None:
                pending_id = identifier(pending_id)
                require(observed_event_id is None or pending_id == observed_event_id)
                observed_event_id = pending_id
            self.evidence.emit("tracking_pending", progress=progress)
            self.pause()

    def final_business(self, order_id: str, shipment_id: str) -> None:
        self.phase = "business_observation"
        shipment = self.get(f"/api/v1/shipments/{shipment_id}")
        require(shipment.get("id") == shipment_id and shipment.get("order_id") == order_id)
        require(shipment.get("status") == "DELIVERED")
        require(shipment.get("status_external_event_id") == self.event_id)
        order = self.get(f"/api/v1/orders/{order_id}")
        require(order.get("id") == order_id and order.get("status") == "FULFILLED")
        self.order_completed = True
        self.evidence.emit(
            "business_completed", shipment_status="DELIVERED", order_status="FULFILLED"
        )

    def notifications(self, event_id: str, *, initial_record: dict[str, Any] | None = None) -> str:
        self.phase = "notifications_observation"
        while True:
            record = (
                initial_record
                if initial_record is not None
                else self.get(f"/api/v1/notification-status/{event_id}")
            )
            initial_record = None
            require(record.get("tracking_event_id") == event_id and record.get("required") is True)
            publication, processing = record.get("publication"), record.get("processing")
            require(publication in ("PENDING", "LEASED", "SENT", "BLOCKED"))
            require(processing in ("NOT_RECEIVED", "PENDING", "RETRY_WAIT", "BLOCKED", "DONE"))
            if publication == "BLOCKED" or processing == "BLOCKED":
                raise Failure("NOTIFICATIONS_BLOCKED", 6)
            if processing == "DONE":
                if record.get("status") == "FAILED":
                    raise Failure("NOTIFICATIONS_FAILED", 6)
                require(record.get("status") == "SIMULATED")
                notification_id = identifier(record.get("notification_id"))
                timestamp(record.get("simulated_at"))
                self.notifications_simulated = True
                self.evidence.emit(
                    "notifications_simulated",
                    notification_id=notification_id,
                    tracking_event_id=event_id,
                    status="SIMULATED",
                )
                return notification_id
            require(record.get("status") is None and record.get("notification_id") is None)
            self.evidence.emit(
                "notifications_pending", publication=publication, processing=processing
            )
            self.pause()

    def single_item(self, path: str) -> dict[str, Any]:
        result = self.get(path)
        items = result.get("items")
        require(type(result.get("total")) is int and result["total"] == 1)
        require(result.get("page") == 1 and result.get("page_size") == 2)
        require(isinstance(items, list) and len(items) == 1 and isinstance(items[0], dict))
        return items[0]

    def effects(self, shipment_id: str, inbox_id: str, event_id: str, notification_id: str) -> None:
        self.phase = "effects_observation"
        event = self.single_item(f"/api/v1/shipments/{shipment_id}/tracking?page_size=2")
        require(event.get("id") == event_id and event.get("inbox_event_id") == inbox_id)
        require(
            event.get("shipment_id") == shipment_id and event.get("application_result") == "APPLIED"
        )
        require(event.get("resulting_shipment_status") == "DELIVERED")
        notification = self.single_item(
            f"/api/v1/notifications?shipment_id={shipment_id}&page_size=2"
        )
        require(
            notification.get("id") == notification_id
            and notification.get("tracking_event_id") == event_id
        )
        require(
            notification.get("shipment_id") == shipment_id
            and notification.get("status") == "SIMULATED"
        )
        self.evidence.emit("effects_observed", tracking_count=1, notifications_count=1)

    def run(self) -> None:
        self.evidence.emit(
            "started",
            run_id=self.run_id,
            event_id=self.event_id,
            expected_application_sha=EXPECTED_APPLICATION_SHA,
            runtime_identity_verified=False,
            carrier=self.config.carrier,
            deadline_seconds=self.config.deadline_seconds,
            request_timeout_seconds=self.config.request_timeout_seconds,
            purpose="functional_smoke",
            unique_events=1,
        )
        order_id, shipment_id, tracking_code = self.prepare()
        raw, headers = self.webhook(tracking_code)
        inbox_id, location = self.admit(raw, headers)
        event_id = self.tracking(inbox_id, location, shipment_id)
        self.final_business(order_id, shipment_id)
        notification_id = self.notifications(event_id)
        self.effects(shipment_id, inbox_id, event_id, notification_id)
        self.phase = "intentional_duplicate"
        duplicate, _ = self.request(
            "POST", f"/api/v1/carriers/{self.config.carrier}/events", 200, raw, headers
        )
        require(
            duplicate.get("result") == "DUPLICATE" and duplicate.get("original_result") == "APPLIED"
        )
        require(
            duplicate.get("external_event_id") == self.event_id
            and duplicate.get("inbox_event_id") == inbox_id
        )
        require(
            duplicate.get("tracking_event_id") == event_id
            and duplicate.get("shipment_id") == shipment_id
        )
        require(
            duplicate.get("previous_status") == "PENDING"
            and duplicate.get("current_status") == "DELIVERED"
        )
        self.effects(shipment_id, inbox_id, event_id, notification_id)
        self.final_business(order_id, shipment_id)
        self.duplicate_verified = True
        self.evidence.emit(
            "duplicate_verified", duplicate_requests=1, tracking_count=1, notifications_count=1
        )

    def summary(self, success: bool, error: str | None = None) -> dict[str, object]:
        return {
            "success": success,
            "error": error,
            "last_operation": self.phase,
            "run_id": self.run_id,
            "event_id": self.event_id,
            "webhook_offered": self.offered,
            "acceptance_observed": self.acceptance_observed,
            "acceptance_verified": self.accepted,
            "tracking_completed": self.tracking_completed,
            "order_completed": self.order_completed,
            "notifications_simulated": self.notifications_simulated,
            "duplicate_verified": self.duplicate_verified,
        }


class SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse's usual error can echo credentials accidentally supplied as an argument.
        del message
        self.exit(2, "Invalid arguments; use --help.\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument(
        "--base-url", required=True, help="Local tunnel or approved private IP HTTPS origin."
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="New directory; parent must exist."
    )
    parser.add_argument("--carrier", choices=tuple(SECRET_ENV), default="carrier-alpha")
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=60,
        help="Entire smoke deadline, 1..300 (default 60).",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=5,
        help="Entire HTTP exchange limit, 0.1..30.",
    )
    parser.add_argument(
        "--poll-seconds", type=float, default=1, help="Read-only polling interval, 0.1..10."
    )
    args = parser.parse_args(argv)
    evidence: Evidence | None = None
    verifier: Verifier | None = None
    evidence_close_failed = False
    try:
        environment = os.environ if environ is None else environ
        config = Config(
            base_url(args.base_url),
            args.output_dir,
            args.carrier,
            args.deadline_seconds,
            args.request_timeout_seconds,
            args.poll_seconds,
            environment.get(SECRET_ENV[args.carrier], ""),
        )
        config.validate()
        evidence = Evidence(config.output_dir)
        verifier = Verifier(config, evidence, transport or HttpTransport())
        verifier.run()
        summary = verifier.summary(True)
        evidence.emit("finished", **summary)
        exit_code = 0
    except (Failure, OSError, KeyboardInterrupt) as error:
        if isinstance(error, Failure):
            code, exit_code = error.code, error.exit_code
        elif isinstance(error, KeyboardInterrupt):
            code, exit_code = "INTERRUPTED_OUTCOME_UNKNOWN", 130
        else:
            code, exit_code = "EVIDENCE_IO_FAILED", 2
        summary = verifier.summary(False, code) if verifier else {"success": False, "error": code}
        if evidence:
            try:
                evidence.emit("failed", **summary)
            except OSError:
                summary["evidence_write_failed"] = True
    finally:
        if evidence:
            try:
                evidence.close()
            except OSError:
                evidence_close_failed = True
    if evidence_close_failed:
        # Cleanup failure is secondary to any earlier failure, including interruption.
        if exit_code == 0:
            exit_code = 2
            summary = verifier.summary(False, "EVIDENCE_IO_FAILED")
        summary["evidence_close_failed"] = True
    print(json.dumps(summary, sort_keys=True), file=sys.stderr if exit_code else sys.stdout)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
