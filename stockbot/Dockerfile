FROM python:3.11-slim

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The bot reads credentials from .env (mount it at runtime, don't bake it in):
#   docker build -t trading-bot .
#   docker run -d --restart unless-stopped --name trading-bot \
#     --env-file .env -v "$PWD":/app trading-bot
CMD ["python", "-m", "bot.main"]
