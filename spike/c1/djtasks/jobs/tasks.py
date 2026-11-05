import time
from pathlib import Path
from django_tasks import task

@task()
def ok(job: str) -> str:
    return f"done {job}"

@task()
def hang(job: str) -> None:
    Path(f"/tmp/djtasks-{job}.started").write_text("1")
    time.sleep(120)
