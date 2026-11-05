"""Spike C1: django-tasks with its database backend on Python 3.14 and Django 5.2."""
import datetime, json, os
os.environ["DJANGO_SETTINGS_MODULE"] = "settings"
import django
django.setup()
from django.db import transaction
from django_tasks_db.models import DBTaskResult
from jobs.tasks import ok, hang
import sys
step = sys.argv[1]
out = {}
if step == "enqueue":
    with transaction.atomic():
        ok.enqueue("rolled-back")
        transaction.set_rollback(True)
    out["enqueue rolled back with its transaction"] = not DBTaskResult.objects.filter(args_kwargs__args=["rolled-back"]).exists()
    ok.enqueue("job-1")
    try:
        ok.enqueue(datetime.datetime(2026, 1, 1))
        out["refuses an argument that is not JSON"] = False
    except Exception as error:
        out["refuses an argument that is not JSON"] = f"{type(error).__name__}"
    hang.enqueue("job-hang")
elif step == "states":
    for row in DBTaskResult.objects.order_by("enqueued_at"):
        out[str(row.args_kwargs.get("args"))] = row.status
print(json.dumps(out))
