"""Exactly one read, independently checked against a known persisted event."""

import json
import sys
import time
from uuid import uuid4

import httpx
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


def run(event, inbox):
    provider = TracerProvider(
        resource=Resource({"service.name": "httpdiag-observer"}), shutdown_on_exit=False
    )
    provider.add_span_processor(
        SimpleSpanProcessor(
            OTLPSpanExporter(endpoint="http://httpdiag-sink:4318/v1/traces", timeout=2)
        )
    )
    tracer = provider.get_tracer("fulfillflow.http.observer", "1")
    request_id = str(uuid4())
    result = {
        "complete": False,
        "offered_business_events": 0,
        "query_count": 0,
        "request_id": request_id,
    }
    try:
        with tracer.start_as_current_span(
            "GET /api/v1/carrier-events",
            kind=SpanKind.CLIENT,
            attributes={"http.request.method": "GET", "http.route": "/api/v1/carrier-events"},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            result["trace_id"] = f"{span.get_span_context().trace_id:032x}"
            headers = {"X-Request-ID": request_id}
            TraceContextTextMapPropagator().inject(headers)
            result["query_count"] = 1
            started = time.monotonic()
            response = httpx.get(
                "http://httpdiag-core:8000/api/v1/carrier-events",
                params={
                    "external_event_id": event,
                    "carrier_code": "carrier-alpha",
                    "page": 1,
                    "page_size": 2,
                },
                headers=headers,
                timeout=10,
                trust_env=False,
            )
            result["response_seconds"] = time.monotonic() - started
            result["status"] = response.status_code
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code != 200:
                raise ValueError("PUBLIC_QUERY_FAILED")
            payload = response.json()
            items = payload.get("items", [])
            if (
                payload.get("total") != 1
                or len(items) != 1
                or items[0].get("external_event_id") != event
                or items[0].get("id") != inbox
                or items[0].get("status") != "APPLIED"
            ):
                raise ValueError("INDEPENDENT_RESULT_MISMATCH")
            result.update(
                complete=True,
                event_id=event,
                inbox_id=inbox,
                persisted_status="APPLIED",
                request_id_echoed=response.headers.get("X-Request-ID") == request_id,
            )
    except Exception as error:
        result["error"] = str(error) if isinstance(error, ValueError) else type(error).__name__
    finally:
        result["flush_completed"] = provider.force_flush(timeout_millis=3000)
        provider.shutdown()
    print(json.dumps(result))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(run(*sys.argv[1:]))
