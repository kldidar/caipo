FROM python:3.14-slim
# Versions under test (spike only). kombu 5.7.0 imports `packaging` in its Redis
# transport without declaring it, so it is installed here by hand (a finding). Celery 5.7.0rc1 is the first release that
# declares Python 3.14; kombu 5.7.0 is its transport.
RUN pip install --no-cache-dir "celery==5.7.0rc1" "kombu==5.7.0" "redis==6.4.0" "psycopg[binary]==3.3.6" "dramatiq[redis]==2.2.1" "packaging"
RUN useradd --uid 10001 --no-create-home worker
WORKDIR /app
COPY *.py /app/
USER 10001
