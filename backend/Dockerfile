FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1

WORKDIR /opt/codemafia
COPY requirements-lock.txt ./
RUN pip install --no-cache-dir --requirement requirements-lock.txt \
    && groupadd --gid 10001 codemafia \
    && useradd --uid 10001 --gid 10001 --home-dir /nonexistent \
       --no-create-home --shell /usr/sbin/nologin codemafia
COPY app/ ./app/

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).close()"

# The room coordinator, connection manager and Yjs bridge require one API
# writer. Multi-worker deployment needs a separate coordination design.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
