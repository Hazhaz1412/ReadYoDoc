FROM python:3.12-slim

WORKDIR /app

# Install system deps for document parsing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/app ./app
COPY backend/run.py ./run.py

# Copy frontend
COPY frontend /frontend

# Create data directories
RUN mkdir -p /data/uploads /data/chroma_db

# Env defaults (overridden by docker-compose)
ENV PYTHONUNBUFFERED=1
ENV UPLOAD_DIR=/data/uploads
ENV CHROMA_DB_PATH=/data/chroma_db

EXPOSE 8000

CMD ["python", "run.py"]
