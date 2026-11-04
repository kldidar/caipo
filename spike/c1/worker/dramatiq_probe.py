"""Spike C1: from the parse container, try to enqueue Dramatiq messages with the parse user."""

import json

import dramatiq
from dramatiq import Message

import dramatiq_app  # noqa: F401  sets the broker from the environment

broker = dramatiq.get_broker()
out = []
for queue, label in (("default", "cannot enqueue a message on another queue"), ("parse", "(finding) enqueue on its own queue")):
    message = Message(queue_name=queue, actor_name="parse_document", args=("TEST",), kwargs={}, options={})
    try:
        broker.enqueue(message)
        out.append({"role": "parse", "req": "3", "check": f"Dramatiq: {label}", "pass": False, "detail": "enqueued"})
    except Exception as error:  # the refusal is recorded
        out.append({"role": "parse", "req": "3", "check": f"Dramatiq: {label}", "pass": True, "detail": f"{type(error).__name__}: {error}"[:160]})
for line in out:
    print(json.dumps(line))
