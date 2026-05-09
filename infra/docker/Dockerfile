ARG NODE_BASE_IMAGE=public.ecr.aws/docker/library/node:20-slim
ARG PYTHON_BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim

FROM ${NODE_BASE_IMAGE} AS ui_builder

WORKDIR /ui

COPY ui/react-dashboard/package.json ./package.json
COPY ui/react-dashboard/package-lock.json ./package-lock.json
RUN npm ci

COPY ui/react-dashboard ./
RUN npm run build


FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --retries 5 --timeout 120 --disable-pip-version-check -r requirements.txt

COPY app ./app
COPY prompts ./prompts
COPY --from=ui_builder /ui/dist ./ui/react-dashboard/dist
COPY .env.example ./.env.example

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]