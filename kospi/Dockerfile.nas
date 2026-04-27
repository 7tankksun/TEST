# 읽기 전용 NAS 웹. 빌드: cd kospi && docker build -f Dockerfile.nas -t kospi-nas-web .
#
# [Synology] 공식 python 이미지 + /app 만 마운트할 때, 실행 명령 예:
#   sh -c "pip install --no-cache-dir 'flask>=3.0' && python /app/app_nas_serve_kospi.py"

FROM python:3.12-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements-nas.txt ./
RUN pip install --no-cache-dir -r requirements-nas.txt

COPY web_templates.py ./
COPY app_nas_serve_kospi.py ./

# /app 을 볼륨으로 덮어도 엔트리는 유지되도록 루트에 둠
COPY entrypoint_nas.sh /entrypoint_nas.sh
RUN chmod +x /entrypoint_nas.sh

ENV PAYLOAD_DIR=/app/payload
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=8501
EXPOSE 8501

ENTRYPOINT ["/entrypoint_nas.sh"]
