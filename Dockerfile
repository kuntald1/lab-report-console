# ============================================================
#  MediCloud Local Backend — Dockerfile
#  Python 3.11 slim image for minimal size
# ============================================================

FROM python:3.11-slim

# Set working directory inside container
WORKDIR /app

# Install system dependencies needed for psycopg2
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker layer caching)
# If requirements.txt doesn't change, this layer is cached
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into container
COPY . .

# Expose port 8001
EXPOSE 8001

# Start the FastAPI server
# host=0.0.0.0 means accept connections from LAN (not just localhost)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
