FROM python:3.13-slim

# xmlsec (needed for SAML signature checks) compiles against the system XML
# security library. lxml is built from source too, so both use the SAME
# libxml2; mixing a wheel-bundled libxml2 with the system one fails at import.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential pkg-config \
      libxml2-dev libxslt1-dev libxmlsec1-dev libxmlsec1-openssl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --no-binary lxml,xmlsec -r requirements.txt

COPY . .
ENV DATA_DIR=/app/data PYTHONUNBUFFERED=1
EXPOSE 8000

# Seed the demo database from the sample legacy export, then serve.
# The migration exits 1 because the sample deliberately contains one bad record; that's expected.
CMD python scripts/migrate.py samples/legacy_export.xml > /dev/null || true; \
    exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
