FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY mattermost_forgejo_enhanced_bridge.py .

# Create directory for SQLite database
RUN mkdir -p /app/data

# Expose port
EXPOSE 5005

# Run the application
CMD ["python", "mattermost_forgejo_enhanced_bridge.py"]