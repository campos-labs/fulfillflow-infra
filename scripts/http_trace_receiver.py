"""Bounded local OTLP sink for a single diagnostic; not a production Collector."""

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler

ALLOWED_ATTRIBUTES = {
    "http.request.method",
    "http.route",
    "http.response.status_code",
    "error.type",
}
SERVICES = {"httpdiag-observer", "httpdiag-core", "httpdiag-tracking"}
ROUTES = {"/api/v1/carrier-events", "/internal/v1/tracking/carrier-events"}


def attributes(values, allowed):
    result = {}
    for item in values:
        if item["key"] not in allowed:
            raise ValueError("UNEXPECTED_ATTRIBUTE")
        value = item["value"]
        if set(value) not in ({"string_value"}, {"int_value"}):
            raise ValueError("UNEXPECTED_ATTRIBUTE_TYPE")
        result[item["key"]] = next(iter(value.values()))
    return result


def identifier(value, length):
    raw = base64.b64decode(value or "", validate=True)
    if len(raw) != length:
        raise ValueError("INVALID_TRACE_ID")
    return raw.hex()


def project(payload):
    rows = []
    for resource in payload.get("resource_spans", []):
        attrs = attributes(resource.get("resource", {}).get("attributes", []), {"service.name"})
        service = attrs.get("service.name")
        if service not in SERVICES:
            raise ValueError("UNEXPECTED_SERVICE")
        for scope in resource.get("scope_spans", []):
            for span in scope.get("spans", []):
                attrs = attributes(span.get("attributes", []), ALLOWED_ATTRIBUTES)
                if (
                    attrs.get("http.route") not in ROUTES
                    or attrs.get("http.request.method") != "GET"
                ):
                    raise ValueError("UNEXPECTED_ROUTE")
                if span.get("name") != "GET " + attrs["http.route"]:
                    raise ValueError("UNEXPECTED_NAME")
                if attrs.get("error.type") not in (
                    None,
                    "transport",
                    "invalid_response",
                    "remote_problem",
                    "remote_http_error",
                    "invalid_content_type",
                    "request_aborted",
                ):
                    raise ValueError("UNEXPECTED_ERROR")
                events = []
                for event in span.get("events", []):
                    if event["name"] not in (
                        "response_received",
                        "content_type_validated",
                    ) or event.get("attributes"):
                        raise ValueError("UNEXPECTED_EVENT")
                    events.append(
                        {"name": event["name"], "time_unix_nano": event["time_unix_nano"]}
                    )
                if (
                    span.get("trace_state")
                    or span.get("links")
                    or span.get("status", {}).get("message")
                ):
                    raise ValueError("UNEXPECTED_CONTEXT_OR_MESSAGE")
                rows.append(
                    {
                        **{
                            key: span.get(key)
                            for key in (
                                "trace_id",
                                "span_id",
                                "parent_span_id",
                                "start_time_unix_nano",
                                "end_time_unix_nano",
                                "kind",
                            )
                        },
                        "trace_id": identifier(span.get("trace_id"), 16),
                        "span_id": identifier(span.get("span_id"), 8),
                        "parent_span_id": identifier(span["parent_span_id"], 8)
                        if span.get("parent_span_id")
                        else None,
                        "service": service,
                        "name": span["name"],
                        "attributes": attrs,
                        "events": events,
                        "status": span.get("status", {}).get("code", 0),
                        "dropped_attributes_count": span.get("dropped_attributes_count", 0),
                        "dropped_events_count": span.get("dropped_events_count", 0),
                    }
                )
    return rows


class Receiver(BaseHTTPRequestHandler):
    lock = threading.Lock()
    records = []
    accepted_batches = 0
    rejected_batches = 0
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def respond(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/snapshot":
            self.respond(404, b"", "text/plain")
            return
        with self.lock:
            payload = json.dumps(
                {
                    "records": self.records,
                    "accepted_batches": type(self).accepted_batches,
                    "rejected_batches": type(self).rejected_batches,
                }
            ).encode()
        self.respond(200, payload, "application/json")

    def do_POST(self):
        from google.protobuf.json_format import MessageToDict
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
            ExportTraceServiceRequest,
        )

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                self.path != "/v1/traces"
                or not 0 < length <= 262144
                or self.headers.get("Content-Encoding")
            ):
                raise ValueError("OTLP_REQUEST")
            request = ExportTraceServiceRequest.FromString(self.rfile.read(length))
            rows = project(MessageToDict(request, preserving_proto_field_name=True))
            with self.lock:
                if len(self.records) + len(rows) > 128:
                    raise ValueError("CAPTURE_LIMIT")
                self.records.extend(rows)
                type(self).accepted_batches += 1
            self.respond(200, b"", "application/x-protobuf")
        except Exception:
            with self.lock:
                type(self).rejected_batches += 1
            self.respond(400, b"", "application/x-protobuf")
            self.close_connection = True


if __name__ == "__main__":
    # Threaded handling prevents an idle keepalive exporter from excluding its peers.
    from http.server import ThreadingHTTPServer

    ThreadingHTTPServer(("0.0.0.0", 4318), Receiver).serve_forever()
