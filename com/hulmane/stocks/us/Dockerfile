FROM python:3.12-slim

WORKDIR /app

# System certs for yfinance HTTPS calls.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8182

# Reads data/formated + data/live (bind-mounted) and serves the dashboard.
CMD ["streamlit", "run", "dashboard.py", \
     "--server.port=8182", "--server.address=0.0.0.0", "--server.headless=true"]
