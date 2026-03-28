FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set python path
ENV PYTHONPATH=/app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
