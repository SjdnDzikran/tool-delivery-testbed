# Shared verifier-only dependency layer; never used as the agent image.
FROM pi-harbor-pilot:corrected-v2
USER root
COPY requirements.txt /opt/verifier-requirements.txt
RUN uv venv --python /usr/local/bin/python3 /opt/verifier \
 && uv pip install --python /opt/verifier/bin/python --require-hashes -r /opt/verifier-requirements.txt
USER study
