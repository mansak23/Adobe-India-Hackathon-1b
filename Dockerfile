# Use a lightweight base image for Python, compatible with AMD64
FROM --platform=linux/amd64 python:3.9-slim-buster

# Set the working directory inside the container
WORKDIR /app

# Copy requirements.txt first to leverage Docker's cache.
# If requirements.txt doesn't change, this layer won't be rebuilt.
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code , includes main.py
COPY . .

# Create input and output directories if they don't exist (important for volume mounts)
RUN mkdir -p input output

# Command to run your application when the container starts
# This matches the expected execution command given in the hackathon brief.
# It tells Python to run main.py
CMD ["python", "main.py"]

