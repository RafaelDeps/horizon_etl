# Stage 1: Build Python dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Chromium + ChromeDriver (auto-versioned pair) + Playwright system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    libxkbcommon0 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libasound2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /usr/local

ENV PATH=/usr/local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    CHROME_BINARY=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    HOME=/tmp

COPY . /app

# Install Playwright's own Chromium + its system deps to a neutral, world-readable path
# (so the app container can run as a non-root user and still find the browsers)
RUN PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/ms-playwright

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

ENTRYPOINT ["python"]
CMD ["src/flows/all.py"]
