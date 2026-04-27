FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app_r1.py candidates_data.py ./

ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=5001

EXPOSE 5001

CMD ["python", "app_r1.py"]
