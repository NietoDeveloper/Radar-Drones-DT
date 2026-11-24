FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install . && useradd --system --uid 10001 radar && mkdir -p /data && chown radar /data
USER radar
# Bind all interfaces inside the container; publish ports deliberately and ALWAYS set an API key.
ENV SDT_RADAR_API_KEY=""
EXPOSE 8080 9100/udp 9101
VOLUME /data
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2).status==200 else 1)"
CMD ["sdt-radar", "serve", "--config", "/app/config/default.toml", "--host", "0.0.0.0"]
