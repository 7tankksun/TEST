# NAS: 웹만 (분석 없음). PAYLOAD_DIR에 로컬에서 생성한 nas_web_payload 내용을 마운트.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "flask>=3.0"
COPY app_nas_serve.py web_templates.py ./
ENV PAYLOAD_DIR=/app/payload
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=5001
EXPOSE 5001
CMD ["python", "app_nas_serve.py"]
