# Use official Python image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies (optional but safe)
RUN apt-get update && apt-get install -y build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of the application code
COPY . .

# Streamlit recommended flags for headless mode
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Expose port (not required but good practice)
EXPOSE 8080

# Cloud Run provides $PORT, expand it using bash
ENTRYPOINT ["bash", "-c", "streamlit run app.py --server.port=$PORT --server.address=0.0.0.0"]
