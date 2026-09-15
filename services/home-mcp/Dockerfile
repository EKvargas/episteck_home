FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/home-mcp
COPY services/home-mcp/pyproject.toml ./pyproject.toml
COPY services/home-mcp/home_mcp ./home_mcp
RUN pip install .
EXPOSE 9932
CMD ["python", "-m", "home_mcp.server"]
