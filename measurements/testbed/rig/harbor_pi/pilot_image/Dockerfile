# Engineering pilot only. Frozen image ID is recorded before model execution.
FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337 AS python
FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c
COPY --from=python /usr/local/ /usr/local/
COPY postgres-key.asc /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
COPY chrome.deb /tmp/chrome.deb
RUN ldconfig && printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && echo 'be1a1e161419f5c8272432f6860912550d8e29985e925913fa800493a0d0c955  /tmp/chrome.deb' | sha256sum -c - \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb postgresql-16 postgresql-client-16 ca-certificates git \
    && rm /tmp/chrome.deb && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/pi
COPY package.json package-lock.json ./
RUN npm install --global npm@11.19.0 && npm ci --omit=dev && test "$(node_modules/.bin/pi --version)" = 1.0.4
COPY uv /usr/local/bin/uv
COPY pg-requirements-resolved.txt /opt/study/
RUN uv venv --python /usr/local/bin/python3 /opt/postgres-mcp \
    && uv pip sync --python /opt/postgres-mcp/bin/python /opt/study/pg-requirements-resolved.txt
COPY bin/ /opt/study/bin/
COPY runner.py execute.py observer.ts fixture.py /opt/study/
ENV PATH=/opt/study/bin:/opt/pi/node_modules/.bin:/opt/postgres-mcp/bin:/usr/lib/postgresql/16/bin:/usr/local/bin:/usr/bin:/bin
RUN /usr/sbin/useradd --create-home --uid 1001 --shell /bin/bash study \
    && mkdir -p /home/study/workspace /home/study/.config/gh-study \
    && chown -R study:study /home/study/workspace /home/study/.config \
    && test "$(bx --version)" = 'bx 1.7.0' \
    && dpkg-query -W > /opt/study/dpkg-packages.txt
WORKDIR /home/study/workspace
USER study
CMD ["sleep", "infinity"]
