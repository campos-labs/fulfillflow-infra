"""Locust HTTP transport with a bounded open arrival schedule; no retries.

Run as a separate process to isolate gevent monkey patching from the observer.
"""

import json
import os
import sys
import time
from pathlib import Path

import gevent
from gevent.pool import Pool
from locust.clients import HttpSession
from locust.env import Environment
from requests.adapters import HTTPAdapter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.scale_contract import dispatch_diagnostic, schedule, utc
from scripts.verify_flow import Config, Verifier, base_url


class Quiet:
    def emit(self, *args, **kwargs):
        pass


def main():
    folder = Path(sys.argv[1])
    settings = json.loads((folder / "load.json").read_text(encoding="utf-8"))
    base = base_url(settings["base"])
    prepared = json.loads((folder / "prepared.json").read_text(encoding="utf-8"))
    offsets = schedule(
        settings["stages"], characterization=settings.get("capacity_characterization", False)
    )
    if len(prepared) != len(offsets):
        raise ValueError("PREPARATION_COUNT")
    env = Environment()
    pool = Pool(settings["http_concurrency"])
    started = time.monotonic()
    with (folder / "admission.jsonl").open("x", encoding="utf-8") as stream:

        def emit(record):
            stream.write(json.dumps({"utc": utc(), **record}) + "\n")
            stream.flush()

        def offer(item):
            session = HttpSession(base, env.events.request, None)
            session.trust_env = False
            session.mount("http://", HTTPAdapter(max_retries=0))
            v = Verifier(
                Config(base, folder, secret=os.environ["CARRIER_ALPHA_WEBHOOK_SECRET"]),
                Quiet(),
                None,
            )
            v.event_id = item["event_id"]
            raw, headers = v.webhook(item["tracking_code"])
            offered = time.monotonic()
            emit({"kind": "offered", "event_id": item["event_id"], "monotonic": offered})
            try:
                response = session.post(
                    "/api/v1/carriers/carrier-alpha/events",
                    data=raw,
                    headers={**headers, "Content-Type": "application/json"},
                    timeout=5,
                    allow_redirects=False,
                    name="webhook admission",
                )
                observed = time.monotonic()
                record = {
                    "kind": "response",
                    "event_id": item["event_id"],
                    "status": response.status_code,
                    "monotonic": observed,
                }
                if response.status_code == 202:
                    try:
                        payload = response.json()
                        from uuid import UUID

                        inbox = str(UUID(payload["inbox_event_id"]))
                        if payload["external_event_id"] != item["event_id"]:
                            raise ValueError("IDENTITY")
                        record["inbox_id"] = inbox
                        record["request_id"] = str(UUID(payload["request_id"]))
                    except (ValueError, KeyError, TypeError):
                        record["schema_error"] = True
                emit(record)
            except Exception:
                # No response body, URL credentials, headers or raw exception exported.
                emit(
                    {"kind": "unknown", "event_id": item["event_id"], "monotonic": time.monotonic()}
                )
            finally:
                session.close()

        for item, offset in zip(prepared, offsets, strict=True):
            gevent.sleep(max(0, started + offset - time.monotonic()))
            dispatch = dispatch_diagnostic(started + offset, time.monotonic(), len(pool), pool.size)
            emit({"kind": "dispatch_attempt", "event_id": item["event_id"], **dispatch})
            if dispatch["reasons"]:
                emit(
                    {
                        "kind": "not_offered",
                        "event_id": item["event_id"],
                        **dispatch,
                    }
                )
            else:
                pool.spawn(offer, item)
        pool.join(timeout=15)
        if len(pool):
            pool.kill()
            raise RuntimeError("ADMISSION_UNFINISHED")
        emit({"kind": "load_finished", "monotonic": time.monotonic()})


if __name__ == "__main__":
    main()
