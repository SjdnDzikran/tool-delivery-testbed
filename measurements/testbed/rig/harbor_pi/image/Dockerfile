# Control integration image only. No capability binaries/credentials/answers.
FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/pi
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && test "$(node_modules/.bin/pi --version)" = 1.0.4
RUN useradd --create-home --uid 1001 --shell /bin/bash study \
    && mkdir -p /home/study/workspace && chown study:study /home/study/workspace
WORKDIR /home/study/workspace
USER study
CMD ["sleep", "infinity"]
