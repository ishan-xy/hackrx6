
FROM python:latest

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt
RUN pip install -U FlagEmbedding

COPY ./ /app/`

EXPOSE 4004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4004"]