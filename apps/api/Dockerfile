FROM python:3.13-alpine AS builder
WORKDIR /build
RUN apk add --no-cache build-base libffi-dev
COPY apps/api/pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.13-alpine
WORKDIR /app
RUN addgroup -S statusforge && adduser -S statusforge -G statusforge && apk add --no-cache libffi wget
COPY --from=builder /install /usr/local
COPY apps/api /app
RUN chown -R statusforge:statusforge /app
USER statusforge
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
