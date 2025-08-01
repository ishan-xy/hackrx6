# Dockerfile

# 1. Use the official Python base image (latest version)
FROM python:latest

# 2. Set the working directory inside the container
WORKDIR /app

# 3. Copy the dependencies file first to leverage Docker cache
COPY ./requirements.txt /app/requirements.txt

# 4. Install the dependencies
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt

# 5. Copy the rest of the application source code
COPY ./ /app/

# 6. Expose the port the app will run on
EXPOSE 4004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4004"]