FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src/ src/

EXPOSE 3333

ENV PYTHONPATH=/app/src

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:3333/health', timeout=3)" || exit 1

CMD ["python", "-m", "unified_router", "start", "--host", "0.0.0.0"]
