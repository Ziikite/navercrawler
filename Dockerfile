FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jre-headless && \
    rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx konlpy

COPY main.py naver.py nlp.py ./
COPY index.html ./frontend/index.html

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
