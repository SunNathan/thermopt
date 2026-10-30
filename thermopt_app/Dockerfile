FROM python:3.13-slim

ARG VERSION=dev
ENV THERMOPT_VERSION=${VERSION} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY thermopt_app/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# The pure logic is shared with the integration: same files, no fork.
COPY custom_components/thermopt/core /app/thermopt_lib/core
COPY custom_components/thermopt/perception/__init__.py \
     custom_components/thermopt/perception/comfort.py \
     custom_components/thermopt/perception/tariff.py \
     custom_components/thermopt/perception/liveness.py \
     /app/thermopt_lib/perception/
COPY custom_components/thermopt/const.py /app/thermopt_lib/const.py
COPY custom_components/thermopt/reporting.py /app/thermopt_lib/reporting.py
RUN touch /app/thermopt_lib/__init__.py

COPY thermopt_app/app /app/app

EXPOSE 8099

# docker --init forwards SIGTERM; the app shuts its tasks down cleanly.
CMD ["python", "-m", "app.main"]
