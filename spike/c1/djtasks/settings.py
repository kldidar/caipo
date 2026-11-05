import os
SECRET_KEY = "TEST-spike-only"
INSTALLED_APPS = ["django_tasks", "django_tasks_db", "jobs"]
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "caipo_djtasks", "USER": os.environ["POSTGRES_USER"], "PASSWORD": os.environ["POSTGRES_PASSWORD"], "HOST": "127.0.0.1", "PORT": os.environ.get("POSTGRES_PORT", "15432")}}
TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}
USE_TZ = True
