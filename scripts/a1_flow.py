"""A1 evidence around the existing frozen-contract functional verifier."""

from __future__ import annotations

import queue
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from scripts import verify_flow as flow
from scripts.a1_runtime import Runtime, check, write_json

FIELDS = {
    "id",
    "external_event_id",
    "inbox_event_id",
    "tracking_event_id",
    "shipment_id",
    "order_id",
    "status",
    "progress",
    "required",
    "publication",
    "processing",
    "notification_id",
    "simulated_at",
    "completed_at",
    "received_at",
    "decided_at",
    "kind",
    "result",
    "previous_status",
    "current_status",
    "event_id",
    "carrier_code",
    "status_external_event_id",
    "application_result",
    "resulting_shipment_status",
    "total",
    "page",
    "page_size",
    "items",
}


def projection(value):
    if isinstance(value, dict):
        return {k: projection(v) for k, v in value.items() if k in FIELDS}
    if isinstance(value, list):
        return [projection(x) for x in value[:3]]
    return value


class Observations(flow.Evidence):
    def __init__(self, path: Path):
        self.started = time.monotonic()
        self.checkpoint = {}
        super().__init__(path)

    def emit(self, phase: str, **fields: object) -> None:
        for key in (
            "run_id",
            "event_id",
            "order_id",
            "shipment_id",
            "inbox_event_id",
            "tracking_event_id",
        ):
            if key in fields:
                self.checkpoint[key] = fields[key]
        super().emit(phase, elapsed_seconds=time.monotonic() - self.started, **fields)


class ObservedVerifier(flow.Verifier):
    def request(self, method, path, expected, body=None, extra_headers=None):
        result, response = super().request(method, path, expected, body, extra_headers)
        if method == "GET":
            self.evidence.emit("public_query", operation=self.phase, response=projection(result))
        return result, response


@contextmanager
def tunnel(runtime: Runtime):
    pods = runtime.get("pods", "-l", "app.kubernetes.io/name=core")["items"]
    check(
        len(pods) == 1 and not pods[0]["metadata"].get("deletionTimestamp"), "CORE_POD_NOT_UNIQUE"
    )
    pod = pods[0]
    statuses = pod.get("status", {}).get("containerStatuses", [])
    check(
        len(statuses) == 1
        and statuses[0].get("ready")
        and statuses[0].get("imageID") == runtime.config.image_id,
        "CORE_IMAGE_NOT_READY",
    )
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    process = subprocess.Popen(
        runtime.prefix()
        + ["port-forward", "pod/" + pod["metadata"]["name"], f"{port}:8000", "--address=127.0.0.1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    ready = queue.Queue()

    def consume():
        for line in process.stdout:
            if line.startswith(f"Forwarding from 127.0.0.1:{port} ->"):
                ready.put(True)

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    try:
        try:
            ready.get(timeout=min(15, runtime.remaining()))
        except queue.Empty:
            raise flow.Failure("PORT_FORWARD_NOT_READY", 3) from None
        check(process.poll() is None, "PORT_FORWARD_EXITED")
        yield (
            f"http://127.0.0.1:{port}",
            {"uid": pod["metadata"]["uid"], "name": pod["metadata"]["name"]},
        )
        check(process.poll() is None, "PORT_FORWARD_EXITED")
        current = runtime.get("pod/" + pod["metadata"]["name"])
        check(current["metadata"]["uid"] == pod["metadata"]["uid"], "CORE_POD_CHANGED")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=2)
        process.stdout.close()


def verify(
    runtime: Runtime, destination: Path, secret: str, *, checkpoint=None, transport=None, base=None
) -> dict:
    def execute(url):
        config = flow.Config(
            url,
            destination,
            deadline_seconds=min(runtime.config.flow_seconds, runtime.remaining()),
            poll_seconds=runtime.config.poll_seconds,
            secret=secret,
        )
        config.validate()
        observations = Observations(destination)
        verifier = ObservedVerifier(config, observations, transport or flow.HttpTransport())
        error = None
        try:
            if checkpoint is None:
                verifier.run()
            else:
                # Read-only recovery observation; never recreates data or reoffers the webhook.
                verifier.event_id = checkpoint["event_id"]
                verifier.run_id = checkpoint["run_id"]
                verifier.offered = verifier.accepted = verifier.acceptance_observed = True
                inbox = flow.identifier(checkpoint["inbox_event_id"])
                shipment = flow.identifier(checkpoint["shipment_id"])
                order = flow.identifier(checkpoint["order_id"])
                observations.emit("resumed_observation", **checkpoint)
                event = verifier.tracking(inbox, f"/api/v1/carrier-events/{inbox}", shipment)
                verifier.final_business(order, shipment)
                notification = verifier.notifications(event)
                verifier.effects(shipment, inbox, event, notification)
        except flow.Failure as failure:
            error = failure.code
        finally:
            observations.close()
        result = verifier.summary(error is None, error)
        if error is None:
            result["verdict"] = "approved"
        elif error in {
            "TRACKING_BLOCKED",
            "TRACKING_REJECTED",
            "NOTIFICATIONS_BLOCKED",
            "NOTIFICATIONS_FAILED",
            "OBSERVATION_DEADLINE",
        }:
            result["verdict"] = "rejected"
        else:
            result["verdict"] = "inconclusive"
        # Deadline before an observed admission cannot prove a business timeout.
        if error == "OBSERVATION_DEADLINE" and not verifier.accepted and checkpoint is None:
            result["verdict"] = "inconclusive"
        result["checkpoint"] = observations.checkpoint
        result["observation_only"] = checkpoint is not None
        write_json(destination / "result.json", result)
        return result

    if base is not None:  # Offline test seam, never exposed by the CLI.
        return execute(base)
    with tunnel(runtime) as (url, identity):
        result = execute(url)
        write_json(destination / "core-identity.json", identity)
        return result
