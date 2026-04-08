FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY manager/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy application code
WORKDIR /app
COPY manager/ /app/

# Copy default whitelist
COPY whitelist-default.txt /opt/whitelist-default.txt

# Copy entrypoint
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Persistent data directory
RUN mkdir -p /data/logs /data/certs /audit

EXPOSE 3128 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
