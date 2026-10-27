# Async Payment Processing Service

Асинхронный микросервис процессинга платежей.

## Стек

- FastAPI
- Pydantic v2
- SQLAlchemy 2.0 async
- PostgreSQL
- RabbitMQ
- FastStream
- aio-pika
- Alembic
- Docker / docker-compose

## Запуск

```bash
cp .env.example .env
docker compose up --build -d