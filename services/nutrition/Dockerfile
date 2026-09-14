FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
# canonical domain package (vendored at build from the repo)
COPY packages/nutrition-domain /srv/packages/nutrition-domain
RUN pip install /srv/packages/nutrition-domain
# service
COPY services/nutrition/pyproject.toml /srv/services/nutrition/pyproject.toml
COPY services/nutrition/app /srv/services/nutrition/app
RUN pip install fastapi uvicorn "pydantic>=2" httpx fastmcp
WORKDIR /srv/services/nutrition
EXPOSE 9930
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","9930"]
