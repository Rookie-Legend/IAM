FROM python:3.11-slim
# Add procps for ps and pkill support
RUN apt-get update && apt-get install -y openvpn easy-rsa iptables iproute2 nano curl procps && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/entrypoint.sh
EXPOSE 4000
EXPOSE 1194/udp
CMD ["/app/entrypoint.sh"]