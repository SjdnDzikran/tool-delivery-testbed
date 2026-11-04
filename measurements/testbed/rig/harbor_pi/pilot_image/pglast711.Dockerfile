# Exact upstream parser required by the pinned PostgreSQL MCP source.
# Parent must resolve to sha256:88559617e80fe5b5d10453e4792d85e84986ace47c82ccec9fdbbeb59cd76102.
FROM pi-harbor-pilot:engineering-v1
USER root
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install --no-deps --python /opt/postgres-mcp/bin/python 'pglast @ git+https://github.com/lelit/pglast@79cfc0d9a22030fdfbc6e47a68d110e2bc95c542' \
    && uv pip check --python /opt/postgres-mcp/bin/python \
    && uv pip freeze --python /opt/postgres-mcp/bin/python > /opt/study/pg-requirements-resolved.txt \
    && dpkg-query -W > /opt/study/dpkg-packages.txt
USER study
