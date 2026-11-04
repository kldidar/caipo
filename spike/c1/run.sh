#!/usr/bin/env bash
# Spike C1: build, run the probes, print one JSON line per check, tear down.
set -uo pipefail
cd "$(dirname "$0")"
# Always start from nothing and leave nothing behind.
docker compose down -v >/dev/null 2>&1 || true
trap 'docker compose down -v >/dev/null 2>&1' EXIT
mkdir -p .secrets && chmod 700 .secrets
pw() { python3 -c 'import secrets; print(secrets.token_hex(16))'; }
TRUSTED_PW=$(pw); PARSE_PW=$(pw); PARSE_CELERY_PW=$(pw); PARSE_DRAMATIQ_PW=$(pw); PG_PW=$(pw)
printf '%s' "$PG_PW" > .secrets/pg
sed -e "s/TRUSTED_PW/$TRUSTED_PW/" -e "s/PARSE_DRAMATIQ_PW/$PARSE_DRAMATIQ_PW/" -e "s/PARSE_CELERY_PW/$PARSE_CELERY_PW/" -e "s/PARSE_PW/$PARSE_PW/" redis/users.acl.template > redis/users.acl
cat > .secrets/trusted.env <<ENV
REDIS_URL=redis://trusted:$TRUSTED_PW@redis:6379/0
CELERY_BROKER_URL=redis://trusted:$TRUSTED_PW@redis:6379/0
DRAMATIQ_BROKER_URL=redis://trusted:$TRUSTED_PW@redis:6379/0
DATABASE_URL=postgresql://postgres:$PG_PW@postgres:5432/postgres
ENV
cat > .secrets/parse.env <<ENV
REDIS_URL=redis://parse:$PARSE_PW@redis:6379/0
CELERY_BROKER_URL=redis://parse_celery:$PARSE_CELERY_PW@redis:6379/0
DRAMATIQ_BROKER_URL=redis://parse_dramatiq:$PARSE_DRAMATIQ_PW@redis:6379/0
ENV
chmod 600 .secrets/*; chmod 644 redis/users.acl
docker compose up -d --build --wait redis postgres >/dev/null 2>&1 || docker compose up -d --build redis postgres >/dev/null
docker compose run --rm init >/dev/null
docker compose up -d --build trusted parse >/dev/null
sleep 3
OUT=$(mktemp)
# Plain Redis lists: the parse probe waits for the job the trusted probe enqueues.
docker compose exec -T parse python probe.py parse > "$OUT.parse" &
PARSE_PID=$!
sleep 2
docker compose exec -T trusted python probe.py trusted >> "$OUT"
wait $PARSE_PID || true
cat "$OUT.parse" >> "$OUT"
# Celery: a worker in the parse container under the parse_celery user.
docker compose exec -d parse celery -A celery_app worker -Q parse -P solo --without-gossip --without-mingle --without-heartbeat --loglevel=INFO --logfile=/tmp/celery.log
sleep 6
docker compose exec -T trusted python celery_probe.py send >> "$OUT"
for _ in $(seq 1 20); do
  if docker compose exec -T trusted test -f /results/celery-job-2.json; then break; fi
  sleep 1
done
if docker compose exec -T trusted test -f /results/celery-job-2.json; then
  echo '{"role": "parse", "req": "5", "check": "Celery: the worker ran the task under its limited user and wrote the result file", "pass": true, "detail": ""}' >> "$OUT"
else
  echo "{\"role\": \"parse\", \"req\": \"5\", \"check\": \"Celery: the worker ran the task under its limited user and wrote the result file\", \"pass\": false, \"detail\": $(docker compose exec -T parse sh -c 'tail -c 600 /tmp/celery.log' | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" >> "$OUT"
fi
docker compose exec -T parse python celery_probe.py forge >> "$OUT" || true
# Dramatiq: a worker in the parse container under the parse_dramatiq user.
docker compose exec -d parse sh -c 'dramatiq dramatiq_app --processes 1 --threads 1 > /tmp/dramatiq.log 2>&1'
sleep 6
docker compose exec -T trusted python -c 'import dramatiq_app; dramatiq_app.parse_document.send("job-3")'
for _ in $(seq 1 20); do
  if docker compose exec -T trusted test -f /results/dramatiq-job-3.json; then break; fi
  sleep 1
done
if docker compose exec -T trusted test -f /results/dramatiq-job-3.json; then
  echo '{"role": "parse", "req": "5", "check": "Dramatiq: the worker ran the task under its limited user and wrote the result file", "pass": true, "detail": ""}' >> "$OUT"
else
  echo "{\"role\": \"parse\", \"req\": \"5\", \"check\": \"Dramatiq: the worker ran the task under its limited user and wrote the result file\", \"pass\": false, \"detail\": $(docker compose exec -T parse sh -c 'grep -i -m3 -E "permission|error" /tmp/dramatiq.log | cut -c1-200' | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')}" >> "$OUT"
fi
docker compose exec -T parse python dramatiq_probe.py >> "$OUT" || true
# Which keys and commands the broker refused, by user (the denials are the evidence).
docker compose exec -T trusted python -c '
import json, os, redis
r = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
seen = set()
for entry in r.acl_log(count=50):
    key = (entry.get("username"), entry.get("reason"), entry.get("object"))
    if key not in seen:
        seen.add(key)
        print(json.dumps({"acl_denied": {"user": key[0], "reason": key[1], "object": key[2]}}))
' >> "$OUT"
cat "$OUT"
