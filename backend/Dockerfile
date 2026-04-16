FROM python:3.11-slim

WORKDIR /src

RUN apt-get update && apt-get install -y msmtp && rm -rf /var/lib/apt/lists/*

COPY . .
RUN chmod 644 /src/msmtprc 
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
