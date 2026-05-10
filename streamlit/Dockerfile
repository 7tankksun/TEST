FROM python:3.11-slim

# 이미지 빌드 시에만 pip 설치. Synology에서 컨테이너 "실행 명령"으로
# pip install 을 매번 돌리지 말고 ENTRYPOINT(또는 entrypoint.sh)만 쓰는 것을 권장합니다.

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# kospi_export_core, apt_analysis_core 등 전체 앱 모듈 포함
COPY . .

# .dockerignore 로 위 데이터 폴더가 빠질 수 있음 — 디렉터리만 만들어 두면 앱에서 mkdir 없이 마운트만 해도 됨
RUN mkdir -p /app/tema_stage2_data /app/tema_cache_data /app/tema_surge_data /app/ML/results \
    && chmod +x /app/entrypoint.sh

EXPOSE 8509

ENTRYPOINT ["/app/entrypoint.sh"]
