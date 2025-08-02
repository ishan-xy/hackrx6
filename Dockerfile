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

EXPOSE 4004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4004"]