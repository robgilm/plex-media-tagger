FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config.json .
COPY run_taggers.py .
CMD ["python", "run_taggers.py"]
