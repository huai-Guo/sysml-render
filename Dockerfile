FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.12.13
COPY src ./src
RUN uv sync --frozen --no-dev && useradd --uid 10001 --create-home app
USER 10001
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
EXPOSE 8081
CMD ["uvicorn", "sysml_render.api:app", "--host", "0.0.0.0", "--port", "8081", "--no-access-log"]
