# build:  cd my_web_USA && docker build -f Dockerfile.nas -t usa-nas-web .
# Synology raw python:  sh -c "pip install 'flask>=3.0' && python3 /app/app_nas_serve_usa.py"
FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements-nas.txt ./
RUN pip install --no-cache-dir -r requirements-nas.txt

COPY web_templates.py ./
COPY app_nas_serve_usa.py ./

COPY entrypoint_nas.sh /entrypoint_nas.sh
RUN chmod +x /entrypoint_nas.sh

ENV PAYLOAD_DIR=/app/payload
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=8504
EXPOSE 8504

ENTRYPOINT ["/entrypoint_nas.sh"]
