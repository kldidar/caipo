"""Spike C1: from the parse container, try to publish a task to another queue with the parse user."""

import json
import sys

from celery_app import app

ROLE = sys.argv[1]
out = []
if ROLE == "forge":
    try:
        app.send_task("spike.forged", args=["TEST"], queue="default")
        out.append({"role": "parse", "req": "3", "check": "Celery: cannot publish a task to another queue", "pass": False, "detail": "published"})
    except Exception as error:  # the refusal is the expected outcome and is recorded
        out.append({"role": "parse", "req": "3", "check": "Celery: cannot publish a task to another queue", "pass": True, "detail": f"{type(error).__name__}: {error}"[:160]})
    # Informational: the limited user still needs LPUSH on its own queue, which
    # kombu uses to restore unacknowledged messages.
    try:
        app.send_task("spike.forged", args=["TEST"], queue="parse")
        out.append({"role": "parse", "req": "3", "check": "Celery (finding): CAN publish to its own queue", "pass": False, "detail": "published; kombu needs LPUSH on its own queue to restore unacknowledged tasks"})
    except Exception as error:  # recorded either way
        out.append({"role": "parse", "req": "3", "check": "Celery (finding): cannot publish to its own queue", "pass": True, "detail": f"{type(error).__name__}: {error}"[:160]})
elif ROLE == "send":
    app.send_task("spike.parse_document", args=["job-2"], queue="parse")
    out.append({"role": "trusted", "req": "6", "check": "Celery: the trusted side sends a task to the parse queue", "pass": True, "detail": ""})
for line in out:
    print(json.dumps(line))
