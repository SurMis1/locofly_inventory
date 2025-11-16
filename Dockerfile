# Use official Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# copy dependencies
COPY requirements.txt requirements.txt

# install python deps
RUN pip install --no-cache-dir -r requirements.txt

# copy everything else
COPY . .

# Streamlit Cloud Run flags
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Expose the correct port (Cloud Run uses PORT env)
EXPOSE 8080

# Cloud Run passes PORT dynamically
ENV PORT=8080

# start Streamlit
CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0
