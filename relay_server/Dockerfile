# ---- Stage 1: Build ----
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Stage 2: Runtime ----
FROM python:3.12-slim

LABEL maintainer="ICC Team"
LABEL description="Integrated Capture Clipboard - Relay Server"

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Expose the default WebSocket + HTTP port
EXPOSE 8765 8766

# Health check via FastAPI /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8766/health')" || exit 1

# Run the relay server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8766", "--ws-ping-interval", "30", "--ws-ping-timeout", "10"]
