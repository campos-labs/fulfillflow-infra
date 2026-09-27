"""One known Service interruption; business state is checked before and after only."""

import json
import time

from scripts import scale_environment as env
from scripts.http_trace_contract import INTERNAL_ROUTE, LABEL, PUBLIC_ROUTE, verify_trace
from scripts.scale_contract import utc, write

NAME = "httpdiag-tracking"


def verify_fault(snapshot, result, injection):
    if not injection.get("confirmed"):
        raise ValueError("FAULT_NOT_INDEPENDENTLY_CONFIRMED")
    if (
        result.get("complete")
        or result.get("status") != 503
        or result.get("error") != "PUBLIC_QUERY_FAILED"
        or result.get("query_count") != 1
        or not result.get("request_id_echoed")
    ):
        raise ValueError("EXPECTED_QUERY_FAILURE_MISSING")
    if snapshot.get("rejected_batches") or not snapshot.get("accepted_batches"):
        raise ValueError("COLLECTION_REJECTED_OR_EMPTY")
    rows = [r for r in snapshot["records"] if r["trace_id"] == result["trace_id"]]
    roles = [
        ("httpdiag-observer", "SPAN_KIND_CLIENT"),
        ("httpdiag-core", "SPAN_KIND_SERVER"),
        ("httpdiag-core", "SPAN_KIND_CLIENT"),
    ]
    if len(rows) != 3 or len({r["span_id"] for r in rows}) != 3:
        raise ValueError("FAULT_TRACE_COVERAGE")
    ordered = []
    for service, kind in roles:
        matches = [r for r in rows if (r["service"], r["kind"]) == (service, kind)]
        if len(matches) != 1:
            raise ValueError("FAULT_TRACE_ROLE")
        ordered.append(matches[0])
    for i, row in enumerate(ordered):
        attrs = row["attributes"]
        if row["parent_span_id"] != (ordered[i - 1]["span_id"] if i else None):
            raise ValueError("FAULT_TRACE_PARENTAGE")
        if (
            attrs.get("http.route") != (INTERNAL_ROUTE if i == 2 else PUBLIC_ROUTE)
            or attrs.get("http.request.method") != "GET"
            or row.get("dropped_attributes_count")
            or row.get("dropped_events_count")
            or int(row["end_time_unix_nano"]) < int(row["start_time_unix_nano"])
        ):
            raise ValueError("FAULT_TRACE_CONTRACT")
        if i == 2:
            if (
                attrs.get("error.type") != "transport"
                or "http.response.status_code" in attrs
                or row.get("events")
                or row.get("status") not in (2, "STATUS_CODE_ERROR")
            ):
                raise ValueError("FAULT_NOT_TRANSPORT")
        elif int(attrs.get("http.response.status_code", 0)) != 503:
            raise ValueError("FAULT_PUBLIC_STATUS")
    return {
        "complete": True,
        "query_outcome": "expected_503",
        "spans": 3,
        "diagnostic_outcome": "core_to_tracking_transport_failure",
        "business_state_during_fault": "not_independently_observed",
        "limit": "Known intervention plus captured client error; missing span alone is not proof.",
    }


def selector_patch(uid, previous, following):
    return [
        {"op": "test", "path": "/metadata/uid", "value": uid},
        {"op": "test", "path": "/spec/selector", "value": previous},
        {"op": "replace", "path": "/spec/selector", "value": following},
    ]


def await_endpoints(runner, available):
    for _ in range(15):
        slices = json.loads(
            runner.kube(
                ["get", "endpointslice", "-l", "kubernetes.io/service-name=" + NAME, "-o", "json"]
            )
        )["items"]
        count = sum(
            e.get("conditions", {}).get("ready") is not False
            for s in slices
            for e in s.get("endpoints", [])
        )
        if bool(count) == available:
            return {"utc": utc(), "ready_endpoints": count}
        time.sleep(1)
    raise RuntimeError("FAULT_ENDPOINTS_NOT_CONVERGED")


def run_sequence(runner, evidence, capture):
    def query(phase, fault=None):
        directory = runner.output / phase
        directory.mkdir(exist_ok=False)
        runner.stage = phase
        snapshot, result = capture(runner, evidence, directory, 3 if fault else 4)
        review = verify_fault(snapshot, result, fault) if fault else verify_trace(snapshot, result)
        write(directory / "review.json", review)
        return result

    before = query("before")
    service = json.loads(runner.kube(["get", "service", NAME, "-o", "json"]))
    labels = service["metadata"].get("labels", {})
    original = service["spec"]["selector"]
    if (
        labels.get(LABEL) != "true"
        or labels.get("fulfillflow.io/http-run") != runner.run_id
        or original != {"app.kubernetes.io/name": NAME}
    ):
        raise RuntimeError("FAULT_SERVICE_IDENTITY")
    uid = service["metadata"]["uid"]
    isolated = {"fulfillflow.io/absent-http-target": runner.run_id}
    # A unique selector targets no pod; ports, exporter and deployments are unchanged.
    if json.loads(
        runner.kube(
            [
                "get",
                "pods",
                "-l",
                "fulfillflow.io/absent-http-target=" + runner.run_id,
                "-o",
                "json",
            ]
        )
    )["items"]:
        raise RuntimeError("FAULT_SELECTOR_NOT_EMPTY")
    injection = {
        "service": NAME,
        "uid": uid,
        "original_selector": original,
        "fault_selector": isolated,
        "confirmed": False,
    }
    try:
        # Finally also runs if a command fails after the API accepted the patch.
        runner.kube(
            [
                "patch",
                "service",
                NAME,
                "--type=json",
                "-p",
                json.dumps(selector_patch(uid, original, isolated)),
            ]
        )
        observed = json.loads(runner.kube(["get", "service", NAME, "-o", "json"]))
        endpoint_state = await_endpoints(runner, False)
        injection.update(
            confirmed=observed["metadata"]["uid"] == uid
            and observed["spec"]["selector"] == isolated,
            endpoint_state=endpoint_state,
        )
        write(runner.output / "injection.json", injection)
        if not injection["confirmed"]:
            raise RuntimeError("FAULT_NOT_CONFIRMED")
        fault = query("fault", injection)
    finally:
        # Restoration bypasses measurement guards, but retains UID and selector CAS.
        observed = json.loads(
            env.kubectl(runner.private, ["get", "service", NAME, "-o", "json"], timeout=15)
        )
        if observed["metadata"]["uid"] != uid or observed["spec"]["selector"] not in (
            original,
            isolated,
        ):
            raise RuntimeError("FAULT_RESTORATION_IDENTITY")
        if observed["spec"]["selector"] == isolated:
            env.kubectl(
                runner.private,
                [
                    "patch",
                    "service",
                    NAME,
                    "--type=json",
                    "-p",
                    json.dumps(selector_patch(uid, isolated, original)),
                ],
                timeout=15,
            )
        restored = json.loads(
            env.kubectl(runner.private, ["get", "service", NAME, "-o", "json"], timeout=15)
        )
        confirmed = restored["metadata"]["uid"] == uid and restored["spec"] == service["spec"]
        write(
            runner.output / "restoration.json",
            {"utc": utc(), "service": NAME, "original_spec_restored": confirmed},
        )
        if not confirmed:
            raise RuntimeError("FAULT_RESTORATION_UNCONFIRMED")
    write(runner.output / "restored-endpoints.json", await_endpoints(runner, True))
    after = query("after")
    if len({r["trace_id"] for r in (before, fault, after)}) != 3:
        raise RuntimeError("PHASE_TRACE_ID_REUSED")
    write(
        runner.output / "review.json",
        {
            "complete": True,
            "query_count": 3,
            "business_writes": 0,
            "expected_http_statuses": [200, 503, 200],
            "independent_restoration": True,
            "state_evidence": "same completed event confirmed before and after; inconclusive during",
            "diagnostic_value": "transport failure located at Core client while business result remains independently confirmed before/after",
            "limits": [
                "Not processing during outage",
                "No SQL or metadata-call spans",
                "No historical incident attribution or causal overhead measurement",
            ],
        },
    )
