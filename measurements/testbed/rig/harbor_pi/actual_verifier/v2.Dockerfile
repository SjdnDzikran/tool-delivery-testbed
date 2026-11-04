# Reuse the retained SQL verifier layer; agent harness and browser pins unchanged.
FROM pi-real-verifier:2026-10-31-v1
USER root
COPY requirements-v2.txt /opt/verifier-requirements-v2.txt
RUN uv pip install --python /opt/verifier/bin/python --require-hashes -r /opt/verifier-requirements-v2.txt
USER study
