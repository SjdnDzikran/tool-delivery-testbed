# Parent frozen at sha256:e383e6cca6c5e612e4ec260ee197429dee2a016260edff02c05440f2b1d02b6c.
FROM pi-harbor-pilot:parser711
USER root
COPY cli_trace.py /opt/study/cli_trace.py
COPY runner.py /opt/study/runner.py
RUN chmod 755 /opt/study/cli_trace.py && mkdir /opt/traced && mkdir /opt/traced/bin \
    && for cli in bx psql playwright-cli gh-github; do ln -s /opt/study/cli_trace.py /opt/traced/bin/$cli; done
ENV PATH=/opt/traced/bin:/opt/study/bin:/opt/pi/node_modules/.bin:/opt/postgres-mcp/bin:/usr/lib/postgresql/16/bin:/usr/local/bin:/usr/bin:/bin
USER study
