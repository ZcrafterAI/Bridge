# Bridge, containerized for KinD. Runs with
# MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE=env (see .env.example / README) since
# there is no OS keychain in here for the local-dev credential-resolver path
# to read -- so credential-resolver's Node/keytar dependency is deliberately
# not installed in this image. z/OSMF credentials come from env vars fed by
# a K8s Secret at deploy time.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mainframe_workflow_mcp/ ./mainframe_workflow_mcp/

ENV MAINFRAME_WORKFLOW_CREDENTIAL_SOURCE=env \
    MAINFRAME_WORKFLOW_MCP_HOST=0.0.0.0 \
    MAINFRAME_WORKFLOW_MCP_PORT=8000 \
    MAINFRAME_WORKFLOW_DB_PATH=/data/state.db

EXPOSE 8000

CMD ["python", "-m", "mainframe_workflow_mcp.server"]
