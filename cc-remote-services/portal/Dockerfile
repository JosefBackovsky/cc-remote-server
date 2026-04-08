FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080 8443

# Default: HTTP only. For HTTPS, set SSL_CERTFILE and SSL_KEYFILE env vars.
CMD ["sh", "-c", "if [ -n \"$SSL_CERTFILE\" ]; then exec uvicorn app:app --host 0.0.0.0 --port 8443 --ssl-certfile $SSL_CERTFILE --ssl-keyfile $SSL_KEYFILE; else exec uvicorn app:app --host 0.0.0.0 --port 8080; fi"]
