FROM python:3.11-slim

WORKDIR /app

# Install git (needed for git+ dependencies) and uv
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN pip install uv

# Copy all source files needed for build
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/

# Install dependencies
RUN uv pip install --system .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/api/v1/health')" || exit 1

# Start the application (migrations run as a k8s initContainer)
CMD ["uvicorn", "github_tamagotchi.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]
