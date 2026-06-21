FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --shell /bin/bash wardn

COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./

RUN pip install --no-cache-dir .

USER wardn

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
