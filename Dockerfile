FROM python:latest

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt
RUN pip install -U FlagEmbedding
RUN pip install google-generativeai

COPY ./ /app

# Make the startup script executable
RUN chmod +x /app/start.sh

EXPOSE 4004

# Set the startup script as the command
CMD ["/app/start.sh"]