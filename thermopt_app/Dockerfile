FROM python:3.13-slim

ARG VERSION=dev
ENV THERMOPT_VERSION=${VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY thermopt_app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY thermopt_app/app /app/app

EXPOSE 8099

# tini (docker --init) forwards SIGTERM; the app shuts down its own loop.
CMD ["python", "-m", "app.main"]
