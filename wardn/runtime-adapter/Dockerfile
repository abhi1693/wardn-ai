FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY adapter ./adapter

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["wardn-runtime-adapter"]
