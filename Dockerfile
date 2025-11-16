# Use official Python image
FROM python:3.10

# Set working directory
WORKDIR /app

# Copy dependency list
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project
COPY . .

# Expose Streamlit default port
EXPOSE 8080

# Run Streamlit
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.address=0.0.0.0"]
