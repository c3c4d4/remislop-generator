# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install FFmpeg
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 5000 available to the world outside this container
EXPOSE 5000

ENV PYTHONUNBUFFERED=1
ENV OUTPUT_DIRECTORY=/app/downloaded_images
ENV DATABASE_PATH=/app/instance/jobs.sqlite3

RUN mkdir -p /app/downloaded_images /app/instance

CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "app:app"]
