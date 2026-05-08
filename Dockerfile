FROM python:3.14-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4 \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

WORKDIR /app
COPY calibre_compat/ calibre_compat/
COPY *.py ./

RUN mkdir -p /app/feeds /app/recipes

VOLUME ["/app/recipes", "/app/feeds"]

ENV RUN_INTERVAL=3600

ENTRYPOINT ["python", "scheduler.py"]
