# 선택: build 쓰면 requirements는 이미지에 박혀서 컨테이너 뜰 때마다 pip 생략
#   docker compose build && docker compose up -d
# portal.py 는 볼륨으로 덮어써서 --reload 만으로 반영
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
EXPOSE 8500
CMD ["gunicorn", "-b", "0.0.0.0:8500", "-w", "1", "--reload", "portal:app"]
