# Use an official Python runtime
FROM python:3.10-slim

# Prevent Python buffering
ENV PYTHONUNBUFFERED True

# Working directory
WORKDIR /app

# Install system dependencies (needed by psycopg2)
RUN apt-get update && apt-get install -y \
    libpq-dev gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Cloud Run sets $PORT automatically
ENV PORT=8080

# Expose the port (Optional, safe to keep)
EXPOSE 8080

# Start Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=$PORT", "--server.address=0.0.0.0"]
