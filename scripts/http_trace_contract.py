"""Pure contracts for the one-query HTTP tracing diagnostic."""

import copy

LABEL = "fulfillflow.io/http-diagnostic"
PUBLIC_ROUTE = "/api/v1/carrier-events"
INTERNAL_ROUTE = "/internal/v1/tracking/carrier-events"


def clone_api(source, role, image):
    if source["metadata"]["name"] != role or role not in ("core", "tracking"):
        raise ValueError("SOURCE_DEPLOYMENT")
    spec = copy.deepcopy(source["spec"])
    name = "httpdiag-" + role
    labels = {
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/part-of": "fulfillflow",
        LABEL: "true",
        "fulfillflow.io/database-client": "true",
    }
    spec["replicas"] = 1
    spec["selector"] = {"matchLabels": {"app.kubernetes.io/name": name}}
    spec["template"]["metadata"] = {"labels": labels}
    spec.pop("strategy", None)
    containers = spec["template"]["spec"]["containers"]
    if len(containers) != 1:
        raise ValueError("SOURCE_CONTAINER_COUNT")
    container = containers[0]
    container["image"] = image
    container["imagePullPolicy"] = "Never"
    overrides = {
        "OTEL_ENABLED": "true",
        "OTEL_SERVICE_NAME": name,
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://httpdiag-sink:4318",
        "OTEL_TRACES_SAMPLER": "parentbased_traceidratio",
        "OTEL_TRACES_SAMPLER_ARG": "1",
    }
    if role == "core":
        overrides["TRACKING_BASE_URL"] = "http://httpdiag-tracking:8000"
    container["env"] = [e for e in container.get("env", []) if e["name"] not in overrides] + [
        {"name": k, "value": v} for k, v in overrides.items()
    ]
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": name, "labels": {LABEL: "true"}},
        "spec": spec,
    }


def verify_trace(snapshot, result):
    if (
        not result.get("complete")
        or result.get("query_count") != 1
        or not result.get("request_id_echoed")
    ):
        raise ValueError("FUNCTIONAL_QUERY_INCOMPLETE")
    if snapshot.get("rejected_batches") or not snapshot.get("accepted_batches"):
        raise ValueError("COLLECTION_REJECTED_OR_EMPTY")
    rows = [r for r in snapshot["records"] if r["trace_id"] == result["trace_id"]]
    if len(rows) != 4 or len({r["span_id"] for r in rows}) != 4:
        raise ValueError("TRACE_COVERAGE")

    def one(service, kind):
        matches = [r for r in rows if r["service"] == service and r["kind"] == kind]
        if len(matches) != 1:
            raise ValueError("TRACE_ROLE")
        return matches[0]

    observer = one("httpdiag-observer", "SPAN_KIND_CLIENT")
    core = one("httpdiag-core", "SPAN_KIND_SERVER")
    client = one("httpdiag-core", "SPAN_KIND_CLIENT")
    tracking = one("httpdiag-tracking", "SPAN_KIND_SERVER")
    if observer["parent_span_id"] or any(
        child["parent_span_id"] != parent["span_id"]
        for parent, child in ((observer, core), (core, client), (client, tracking))
    ):
        raise ValueError("TRACE_PARENTAGE")
    for row in rows:
        attrs = row["attributes"]
        expected_route = PUBLIC_ROUTE if row in (observer, core) else INTERNAL_ROUTE
        if (
            attrs.get("http.route") != expected_route
            or attrs.get("http.request.method") != "GET"
            or row.get("status") in (2, "STATUS_CODE_ERROR")
        ):
            raise ValueError("TRACE_ROUTE_OR_ERROR")
        if (
            int(attrs.get("http.response.status_code", 0)) != 200
            or attrs.get("error.type")
            or row.get("dropped_attributes_count")
            or row.get("dropped_events_count")
        ):
            raise ValueError("TRACE_STATUS_OR_DROPS")
        if int(row["end_time_unix_nano"]) < int(row["start_time_unix_nano"]):
            raise ValueError("TRACE_CLOCK")
    if [e["name"] for e in client["events"]] != ["response_received", "response_validated"]:
        raise ValueError("VALIDATION_BOUNDARY_MISSING")
    return {
        "complete": True,
        "spans": 4,
        "parentage_verified": True,
        "functional_check_independent_of_spans": True,
        "durations_ms": {
            role: (int(row["end_time_unix_nano"]) - int(row["start_time_unix_nano"])) / 1e6
            for role, row in (
                ("observer", observer),
                ("core_server", core),
                ("internal_operation_including_validation", client),
                ("tracking_server", tracking),
            )
        },
        "clock_limit": "Do not subtract nested/overlapping spans or infer SQL commit timing.",
        "export_limit": "Receiver acceptance and expected coverage; no claim of general exporter health or overhead.",
    }
