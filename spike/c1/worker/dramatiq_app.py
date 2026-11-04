"""Spike C1: a Dramatiq actor whose worker runs under a Redis user limited to its own keys."""

import json
import os
from pathlib import Path

import dramatiq
from dramatiq.brokers.redis import RedisBroker

dramatiq.set_broker(RedisBroker(url=os.environ["DRAMATIQ_BROKER_URL"]))


@dramatiq.actor(queue_name="parse")
def parse_document(job: str) -> None:
    text = Path("/artifacts/doc-1.txt").read_text()
    Path(f"/results/dramatiq-{job}.json").write_text(json.dumps({"job": job, "text_length": len(text)}))
