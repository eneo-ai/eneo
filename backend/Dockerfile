FROM python:3.11

# Install ffmpeg
RUN apt-get -y update
RUN apt-get -y upgrade
RUN apt-get install -y ffmpeg

# Install libmagic, for mimetypes
RUN apt-get install libmagic1

RUN pip install poetry

WORKDIR /code

COPY ./pyproject.toml ./poetry.lock ./

COPY . /code/

RUN poetry config virtualenvs.create false \
  && poetry install --no-interaction --no-ansi

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Handle tiktoken to be able to run in disconnected mode
ENV TIKTOKEN_CACHE_DIR=/tiktoken
RUN mkdir /tiktoken
ADD --chmod=644 https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken /tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4

# Run as unpriviledged user
USER 1000

CMD ["sh", "-c", "./run.sh"]
