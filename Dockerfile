FROM python:3.13-slim
WORKDIR /app
COPY lead_agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lead_agent/ lead_agent/
COPY ui/ ui/
COPY server.py access.py ./
# Cloud Run runs as the service's own account: no gcloud sign-in in the image.
# Conversations and workbooks are in memory only (server.py).
ENV HOST=0.0.0.0 PORT=8080
CMD ["python", "server.py"]
