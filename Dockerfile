FROM python:3.11-slim

WORKDIR /app

# Install uv for fast dependency management
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

# Run the application
CMD ["uvicorn", "github_tamagotchi.main:app", "--host", "0.0.0.0", "--port", "8000"]
