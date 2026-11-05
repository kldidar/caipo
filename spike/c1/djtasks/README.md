# django-tasks with its database backend (trusted work only)

Python 3.14.4, Django 5.2.17, django-tasks 0.12.0, django-tasks-db 0.13.0, against a
scratch PostgreSQL database. Run on 2026-11-05:

1. `migrate`, then `python probe.py enqueue`: an enqueue inside a transaction that is
   rolled back leaves no task; an argument that is not JSON (a datetime) is refused
   with `TypeError`.
2. `db_worker` ran `job-1` (SUCCESSFUL) and started `job-hang`; the worker was killed
   with SIGKILL mid-task.
3. `python probe.py states`: `job-hang` stays RUNNING. A second `db_worker --batch`
   exits without touching it. Nothing recovers or counts an orphaned task: a reaper is
   needed, as for every other candidate.

A database-backed queue cannot serve the isolated workers, which hold no database
credentials (ADR-0011 requirement 1). It is evaluated for trusted work only.
