FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

# Copy source
COPY aegisml/ ./aegisml/

# Expose
EXPOSE 8000

# Run
CMD ["uvicorn", "aegisml.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
