FROM python:3.11-slim

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY main.py .
COPY services/ ./services/
COPY dk_airfields.json .

# Create directories for data storage
RUN mkdir -p /data /events
VOLUME /data
VOLUME /events

# Set basic environment variables
ENV PYTHONUNBUFFERED=1
ENV AIRFIELDS_FILE=/app/dk_airfields.json

# Expose the WebSocket port
EXPOSE 8765

# Run the application
CMD ["python", "main.py"] 