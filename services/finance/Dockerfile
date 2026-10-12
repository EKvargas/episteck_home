FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/services/finance
COPY services/finance/pyproject.toml ./pyproject.toml
COPY services/finance/app ./app
RUN pip install .
# One image, three commands: the API (default), the MCP server (python -m app.mcp.server)
# and the sync job (python -m app.sync). Ports are published on loopback by the Quadlet.
EXPOSE 9935 9936
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9935"]
