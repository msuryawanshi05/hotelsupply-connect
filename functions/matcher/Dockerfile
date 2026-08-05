# Deliverable: Serverless-style function container
# Designed for Knative Service deployment on OpenShift Serverless (scale-to-zero)
# Non-root user, minimal base image
FROM python:3.11-slim

RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY handler.py .

RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/healthz')" || exit 1

CMD ["uvicorn", "handler:app", "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
