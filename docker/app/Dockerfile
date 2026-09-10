FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency configuration files
COPY pyproject.toml uv.lock ./

# Sync project dependencies
RUN uv sync --frozen --no-dev

# Copy source files
COPY src/ src/
COPY migrations/ migrations/
COPY alembic.ini ./

# Expose port
EXPOSE 8000

# Default command to run migrations and start the server
CMD ["uv", "run", "fastapi", "run", "src/kb_web/server.py", "--host", "0.0.0.0", "--port", "8000"]
