FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app app
COPY prompts prompts
COPY data/profile.md data/profile.md

RUN useradd --create-home agent
USER agent

# cloud run passes the port in $PORT
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
