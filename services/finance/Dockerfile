FROM python:3.11-slim
# Dependencies come only from requirements.lock: exact versions with SHA-256 hashes, so a
# rebuild of the same commit installs the same code. The package itself is installed with
# --no-deps and --no-build-isolation (the base image's setuptools builds it), so pip
# downloads nothing that is not in the lock. `pip check` fails the build if the lock and
# pyproject.toml disagree.
#
# Refresh the lock deliberately, from services/finance (Linux x86_64 target, like the node):
#   uv pip compile pyproject.toml --python-version 3.11 --python-platform x86_64-manylinux_2_40 \
#     --generate-hashes --no-annotate --upgrade \
#     --custom-compile-command "see the header of services/finance/Dockerfile" -o requirements.lock
# Drop --upgrade to keep current pins and only add what pyproject.toml now needs. Then run
# the Finance tests in a venv installed from the lock and rebuild the image.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/services/finance
COPY services/finance/requirements.lock ./requirements.lock
RUN pip install --require-hashes --no-deps -r requirements.lock
COPY services/finance/pyproject.toml ./pyproject.toml
COPY services/finance/app ./app
RUN pip install --no-deps --no-build-isolation .
RUN pip check
# One image, three commands: the API (default), the MCP server (python -m app.mcp.server)
# and the sync job (python -m app.sync). Ports are published on loopback by the Quadlet.
EXPOSE 9935 9936
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9935"]
