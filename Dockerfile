FROM python:3.10-slim AS builder

WORKDIR /app

COPY requirements.txt .

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.10-slim AS runtime

WORKDIR /app

RUN groupadd --gid 1001 etlgroup && \
    useradd --uid 1001 --gid etlgroup --shell /bin/bash --create-home etluser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY etl_pipeline.py .
COPY app.py .
COPY .env .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

RUN mkdir -p /app/data_source /app/logs && \
    chown -R etluser:etlgroup /app

RUN apt-get update && apt-get install -y --no-install-recommends gosu && \
    rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8050

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import etl_pipeline; print('OK')" || exit 1

ENTRYPOINT ["/entrypoint.sh"]

CMD ["python", "app.py"]