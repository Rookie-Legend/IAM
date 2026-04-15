FROM python:3.11-slim
RUN apt-get update && apt-get install -y openvpn easy-rsa netcat-traditional iptables iproute2 nano curl procps tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/entrypoint.sh /app/client-connect.sh /app/client-disconnect.sh /app/session_sync.py
RUN mkdir -p /etc/openvpn && chmod 755 /etc/openvpn
EXPOSE 4000 1194/udp
RUN sed -i 's/\r$//' /app/entrypoint.sh /app/client-connect.sh /app/client-disconnect.sh /app/session_sync.py
CMD ["/app/entrypoint.sh"]