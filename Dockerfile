# Backend (FastAPI). It never executes generated code itself: it only launches the
# locked-down sandbox image through app/docker_wrapper.py (fixed argv, no shell).
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337
ARG DOCKER_CLI_VERSION=27.3.1
ADD https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz /tmp/docker.tgz
RUN tar xzf /tmp/docker.tgz --strip-components=1 -C /usr/local/bin docker/docker && rm /tmp/docker.tgz
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY trusted ./trusted
# Integrity manifest also pins control-plane and runner source outside /trusted.
# Stage the exact same reviewed files in the immutable backend image.
COPY sandbox ./sandbox
COPY Dockerfile ./Dockerfile
COPY docker-compose.yml ./docker-compose.yml
COPY deploy.sh ./deploy.sh
COPY scripts ./scripts
COPY VERSIONS ./VERSIONS
ENV PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/mpl PYTHONPATH=/srv
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
