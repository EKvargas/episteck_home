FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv/home-bff
COPY services/home-bff/pyproject.toml ./pyproject.toml
COPY services/home-bff/home_bff ./home_bff
RUN pip install .
EXPOSE 9933
# Secrets arrive via EnvironmentFile at run time. Nothing secret is baked into a layer.
CMD ["python", "-m", "home_bff"]
