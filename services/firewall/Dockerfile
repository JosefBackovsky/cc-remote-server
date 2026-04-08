FROM ubuntu/squid:latest

# Install Python 3 for Firewall Manager
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Firewall Manager dependencies
COPY manager/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# Copy Firewall Manager code
WORKDIR /app
COPY manager/ /app/

# Copy Squid configuration
COPY squid.conf /opt/squid.conf
COPY whitelist-default.txt /opt/whitelist-default.txt

# Copy custom error page
COPY ERR_BLOCKED /usr/share/squid/errors/en/ERR_BLOCKED

# Copy entrypoint
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Persistent data directory
RUN mkdir -p /data/logs

EXPOSE 3128 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
