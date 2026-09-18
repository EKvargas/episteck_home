FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
# canonical domain package (vendored at build from the repo)
COPY packages/nutrition-domain /srv/packages/nutrition-domain
RUN pip install /srv/packages/nutrition-domain
# service
WORKDIR /srv/services/nutrition
COPY services/nutrition/pyproject.toml ./pyproject.toml
COPY services/nutrition/app ./app
RUN pip install .
EXPOSE 9930
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","9930"]
