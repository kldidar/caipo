"""Spike C1 probes: what an isolated worker can and cannot do. Prints one JSON line per check."""

import json
import os
import socket
import sys
import time
from pathlib import Path

import redis

ROLE = sys.argv[1]
results: list[dict[str, object]] = []


def check(requirement: str, name: str, passed: bool, detail: str = "") -> None:
    results.append({"role": ROLE, "req": requirement, "check": name, "pass": passed, "detail": detail[:160]})


def refused(call) -> tuple[bool, str]:
    try:
        call()
    except Exception as error:  # the refusal is the expected outcome and is recorded
        return True, f"{type(error).__name__}: {error}"
    return False, "allowed"


def reachable(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=3):
            return True, "connected"
    except OSError as error:
        return False, f"{type(error).__name__}: {error}"


if ROLE == "parse":
    env = " ".join(sorted(os.environ))
    check("1", "no database credentials in the environment", not any(k for k in os.environ if k.startswith(("POSTGRES", "DATABASE", "PG"))), env)
    ok, detail = reachable("postgres", 5432)
    check("1", "PostgreSQL is not reachable", not ok, detail)
    check("2", "no AI provider credentials in the environment", not any(k for k in os.environ if "API_KEY" in k or k.startswith(("OPENAI", "ANTHROPIC"))), env)
    ok, detail = reachable("trusted", 22)
    check("4", "the trusted worker's host is not reachable", not ok, detail)
    ok, detail = reachable("redis", 6379)
    check("4", "the broker is reachable", ok, detail)
    for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        ok, detail = reachable(host, port)
        check("8", f"no outbound connection to {host}:{port}", not ok, detail)
    try:
        socket.getaddrinfo("example.com", 443)
        check("8", "no name resolution of external hosts", False, "resolved")
    except OSError as error:
        check("8", "no name resolution of external hosts", True, str(error))

    r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    # Wait for the trusted side to enqueue a job, then take it reliably.
    job = r.blmove("q:parse", "q:parse:processing", timeout=20, src="RIGHT", dest="LEFT")
    check("3", "takes a job from its own queue", job is not None, str(job))
    for label, call in (
        ("cannot push to another queue", lambda: r.lpush("q:default", "TEST forged")),
        ("cannot push to its own queue either", lambda: r.lpush("q:parse", "TEST forged")),
        ("cannot take from another queue", lambda: r.blmove("q:default", "q:parse:processing", timeout=1)),
        ("cannot read another key", lambda: r.get("secret")),
        ("cannot publish on a channel", lambda: r.publish("events", "TEST")),
        ("cannot list keys", lambda: r.keys("*")),
        ("cannot change the server's configuration", lambda: r.config_get("*")),
    ):
        ok, detail = refused(call)
        check("3", label, ok, detail)

    # Requirement 9: the artifact is readable, the artifact store is not writable.
    try:
        content = Path("/artifacts/doc-1.txt").read_text()
        check("9", "reads the artifact", content.startswith("TEST"), content.strip())
    except OSError as error:
        check("9", "reads the artifact", False, str(error))
    ok, detail = refused(lambda: Path("/artifacts/forged.txt").write_text("TEST"))
    check("9", "cannot write to the artifact store", ok, detail)
    ok, detail = refused(lambda: Path("/app/forged.py").write_text("TEST"))
    check("9", "cannot write to its own filesystem", ok, detail)
    # Requirement 5: the result goes out only as a file.
    if job:
        Path(f"/results/{job}.json").write_text(json.dumps({"job": job, "text_length": 13}))
        r.lrem("q:parse:processing", 1, job)
        check("5", "writes its result as a file in the results area", Path(f"/results/{job}.json").exists())

elif ROLE == "trusted":
    import psycopg

    r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    r.set("secret", "TEST secret the parse worker must not read")
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as db:
        db.execute("CREATE TABLE IF NOT EXISTS attempt (job text PRIMARY KEY, attempts int NOT NULL)")
        # Attempts are counted by the trusted side before each dispatch (ADR-0004).
        db.execute("INSERT INTO attempt VALUES ('job-1', 1) ON CONFLICT (job) DO UPDATE SET attempts = attempt.attempts + 1")
        r.lpush("q:parse", "job-1")
        check("6", "enqueues a job with its attempt counted in PostgreSQL", True)
        deadline = time.time() + 30
        result = Path("/results/job-1.json")
        while time.time() < deadline and not result.exists():
            time.sleep(0.5)
        try:
            data = json.loads(result.read_text())
            valid = set(data) == {"job", "text_length"} and data["job"] == "job-1" and isinstance(data["text_length"], int)
            check("6", "learns of completion from the result file alone, and validates it", valid, str(data))
        except (OSError, ValueError) as error:
            check("6", "learns of completion from the result file alone, and validates it", False, str(error))
        check("3", "nothing appeared on another queue", r.llen("q:default") == 0, f"q:default length {r.llen('q:default')}")

for line in results:
    print(json.dumps(line))
