FROM python:3.13-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your main script
COPY main.py .

# Run the Python script directly
CMD ["python", "main.py"]
