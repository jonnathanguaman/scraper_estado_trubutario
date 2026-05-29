FROM mcr.microsoft.com/playwright/python:v1.59.0-noble

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SRI_HEADLESS=true
ENV SRI_PROFILE_DIR=/app/storage/browser-profile
ENV SRI_SCREENSHOT_DIR=/app/storage/screenshots

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    python -m camoufox fetch

COPY app ./app

RUN mkdir -p /app/storage/browser-profile /app/storage/screenshots /app/storage/capturas

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
