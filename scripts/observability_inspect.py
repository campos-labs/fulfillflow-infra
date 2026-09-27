"""Read the previously offered event through Core; never submit business writes."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import observability_pilot as pilot
from scripts.a1_flow import projection, tunnel
from scripts.a1_runtime import Config, Runtime
from scripts.scale_calibration import verify_images, wait_api
from scripts.scale_contract import CLUSTER, RUNTIME_CONFIG, SOURCE, write
from scripts.scale_diagnostic import TimedTransport
from scripts.verify_flow import HttpTransport

env = pilot.env


def project_result(response, event):
    if response.status != 200:
        return {"query_status": response.status, "finding": "inconclusive"}
    payload = json.loads(response.body)
    items = payload.get("items")
    if not isinstance(items, list) or type(payload.get("total")) is not int:
        raise RuntimeError("INBOX_SCHEMA")
    if payload["total"] not in (0, 1) or len(items) != payload["total"]:
        raise RuntimeError("INBOX_COUNT")
    if items and items[0].get("external_event_id") != event:
        raise RuntimeError("INBOX_EVENT_MISMATCH")
    return {
        "query_status": 200,
        "finding": "record_found" if items else "no_record_returned",
        "items": projection(items),
    }


def inspect_event(private, output):
    identity = json.loads((private / "identity.json").read_bytes())
    env.command(["docker", "start", identity["container_id"]])
    wait_api(private)
    for name in ("core", "tracking", "notifications", *pilot.WORKERS):
        env.kubectl(
            private, ["rollout", "status", "deployment/" + name, "--timeout=120s"], timeout=130
        )
    verify_images(private, identity)
    ns = json.loads(env.kubectl(private, ["get", "namespace", "fulfillflow", "-o", "json"]))
    if ns["metadata"]["uid"] != identity["namespace_uid"]:
        raise RuntimeError("NAMESPACE_IDENTITY")
    pilot.wait_workers(private, output / "worker-startup.jsonl")
    tool, _ = env.tools()
    config = Config(
        str(tool),
        env.executable("docker"),
        str(private / "kubeconfig"),
        "kind-" + CLUSTER,
        "fulfillflow",
        identity["namespace_uid"],
        CLUSTER + "-control-plane",
        env.IMAGE,
        RUNTIME_CONFIG,
    )
    config.validate()
    event = json.loads((output / "input.json").read_bytes())["event_id"]
    transport = TimedTransport(HttpTransport())
    try:
        with tunnel(Runtime(config)) as (url, _):
            # Exact ID + carrier filter; no signature, payload or secret is needed for GET.
            query = urlencode(
                {
                    "external_event_id": event,
                    "carrier_code": "carrier-alpha",
                    "page": 1,
                    "page_size": 2,
                }
            )
            response = transport(
                "GET",
                url + "/api/v1/carrier-events?" + query,
                {"Accept": "application/json", "X-Request-ID": str(uuid4())},
                None,
                10,
            )
            result = project_result(response, event)
            result.update(
                event_id=event,
                new_events_offered=0,
                limit="State returned after runtime restart; does not reconstruct the original admission or identify the cause of the historical 503.",
            )
            write(output / "inspection.json", result)
    finally:
        write(output / "http-timings.json", transport.records)


def execute(private, output, source):
    if CLUSTER != pilot.EXPECTED_CLUSTER or output.exists():
        raise RuntimeError("EXCLUSIVE_OBSERVABILITY_OUTPUT_REQUIRED")
    host = pilot.guard(5)
    original = (source / "functional.json").read_bytes()
    functional = json.loads(original)
    event = functional["event_id"]
    UUID(event.removeprefix("infra-smoke-"))
    if (
        not event.startswith("infra-smoke-")
        or not functional.get("webhook_offered")
        or functional.get("acceptance_verified")
    ):
        raise RuntimeError("UNEXPECTED_SOURCE")
    identity = json.loads((private / "identity.json").read_bytes())
    if identity["source"] != SOURCE:
        raise RuntimeError("APPLICATION_IDENTITY")
    node = json.loads(env.command(["docker", "inspect", CLUSTER + "-control-plane"]))[0]
    if (
        node["Id"] != identity["container_id"]
        or node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER
        or node["State"]["Running"]
    ):
        raise RuntimeError("NODE_IDENTITY")
    if env.command(["docker", "ps", "-q"]).strip():
        raise RuntimeError("CONCURRENT_CONTAINERS")
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "input.json",
        {
            "event_id": event,
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "host": host,
            "infrastructure_sha": env.command(["git", "rev-parse", "HEAD"]).strip(),
        },
    )
    complete, stopped, error = False, False, None
    try:
        pilot.stage("inspect", private, output)
        complete = True
    except Exception as failure:
        error = str(failure) if isinstance(failure, RuntimeError) else type(failure).__name__
    finally:
        try:
            env.command(["docker", "stop", "--timeout", "30", node["Id"]], timeout=60)
            stopped = not json.loads(env.command(["docker", "inspect", node["Id"]]))[0]["State"][
                "Running"
            ]
        except Exception:
            error = error or "SHUTDOWN_UNCONFIRMED"
        result = {
            "complete": complete and stopped,
            "error": error,
            "container_stopped": stopped,
            "new_events_offered": 0,
        }
        write(output / "summary.json", result)
    print(json.dumps(result))
    return 0 if result["complete"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("private", "output", "source"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    lock = env.ROOT / "artifacts/observability-pilot.lock"
    try:
        with lock.open("x"):
            pass
        try:
            return execute(args.private.resolve(), args.output.resolve(), args.source.resolve())
        finally:
            lock.unlink()
    except Exception as failure:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error": str(failure)
                    if isinstance(failure, RuntimeError)
                    else type(failure).__name__,
                    "new_events_offered": 0,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
