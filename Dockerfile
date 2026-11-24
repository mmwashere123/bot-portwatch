FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=0 playwright install chromium
COPY . .

CMD ["python", "bot.py"]
