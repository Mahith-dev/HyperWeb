# Use a lightweight official Python image
FROM python:3.10-slim

# Install system dependencies (FFmpeg for merging, Aria2 for acceleration)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    aria2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up a working directory
WORKDIR /code

# Copy requirements and install Python dependencies
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Create a clean temporary directory for our downloads
RUN mkdir -p /tmp/hyper_downloads && chmod 777 /tmp/hyper_downloads

# Copy the application source code
COPY . .

# Expose the mandatory Hugging Face port
EXPOSE 8000

# Command to fire up the server
CMD ["python", "main.py"]