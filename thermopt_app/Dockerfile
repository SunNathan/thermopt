FROM python:3.13-slim

ARG VERSION=dev
ENV THERMOPT_VERSION=${VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY thermopt_app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Pure logic: no Home Assistant import, shared with the tests.
COPY lib/thermopt_lib /app/thermopt_lib

COPY thermopt_app/app /app/app

EXPOSE 8099

# docker --init forwards SIGTERM; the app shuts its tasks down cleanly.
CMD ["python", "-m", "app.main"]
