FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Runはデフォルトで8080ポートを期待するので、8080で起動します
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]