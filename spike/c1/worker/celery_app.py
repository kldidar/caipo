"""Spike C1: a Celery app whose parse worker runs under a Redis user limited to its own keys."""

import json
import os
from pathlib import Path

from celery import Celery

app = Celery("spike")
app.conf.update(
    broker_url=os.environ["CELERY_BROKER_URL"],
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_enable_remote_control=False,
    worker_send_task_events=False,
    task_default_queue="default",
    task_routes={"spike.parse_document": {"queue": "parse"}},
    # Per-queue bookkeeping keys, so that the parse user's ACL can name them.
    broker_transport_options={
        "unacked_key": "unacked:parse",
        "unacked_index_key": "unacked_index:parse",
        "unacked_mutex_key": "unacked_mutex:parse",
        "visibility_timeout": 60,
    },
    broker_connection_retry_on_startup=False,
)


@app.task(name="spike.parse_document")
def parse_document(job: str) -> None:
    text = Path("/artifacts/doc-1.txt").read_text()
    Path(f"/results/celery-{job}.json").write_text(json.dumps({"job": job, "text_length": len(text)}))
