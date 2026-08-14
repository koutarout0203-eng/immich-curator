FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 curator
WORKDIR /app
COPY pyproject.toml README.md ./
COPY curator ./curator
RUN pip install --no-cache-dir . && mkdir -p /data && chown curator:curator /data

USER curator
VOLUME ["/data"]
ENTRYPOINT ["immich-curator"]
CMD ["snapshot"]
