FROM python:3.11-slim

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY main.py .
COPY services/ ./services/


# Set basic environment variables
ENV PYTHONUNBUFFERED=1

# Expose the WebSocket port
EXPOSE 8765

# Run the application
CMD ["python", "main.py"] 