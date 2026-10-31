FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY turnproof ./turnproof
COPY verify_packet.py scripts ./
COPY config ./config
RUN pip install --no-cache-dir -e .
EXPOSE 8080
CMD ["uvicorn", "turnproof.review.app:app", "--host", "0.0.0.0", "--port", "8080"]
