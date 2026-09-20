FROM python:3.12-slim
WORKDIR /app
# Dependency installation is cached independently from application code.
COPY backend/requirements.lock /app/backend/requirements.lock
RUN pip install --no-cache-dir -c /app/backend/requirements.lock alembic sqlalchemy fastapi uvicorn httpx pydantic-settings PyYAML langchain langchain-openai langgraph "psycopg[binary]"
COPY backend /app/backend
RUN pip install --no-cache-dir --no-deps /app/backend
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
COPY config /app/config
COPY skills /app/skills
RUN useradd -m app
ENV CONFIG_PATH=/app/config/settings.yaml SKILLS_DIR=/app/skills
USER app
CMD ["uvicorn", "troubleshooter.api.agent:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001"]
