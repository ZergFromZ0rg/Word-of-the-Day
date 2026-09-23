FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api]"

# The starter word list; copied to /data on first run if you don't provide your own.
COPY words.txt /opt/words.txt

RUN useradd --create-home app && mkdir /data && chown app /data
USER app

ENV WOTD_HOST=0.0.0.0 \
    WOTD_PORT=8000 \
    WOTD_WORDS_FILE=/data/words.txt \
    WOTD_HISTORY_FILE=/data/history.json \
    WOTD_CACHE_DIR=/data/cache
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["sh", "-c", "[ -f \"$WOTD_WORDS_FILE\" ] || cp /opt/words.txt \"$WOTD_WORDS_FILE\"; exec word-of-the-day-api"]
