FROM python:3.11

# Install ffmpeg
RUN apt-get -y update
RUN apt-get -y upgrade
RUN apt-get install -y ffmpeg

# Install libmagic, for mimetypes
RUN apt-get install libmagic1

# Install poetry
RUN pip install poetry

WORKDIR /code

COPY ./pyproject.toml ./poetry.lock ./

COPY . /code/

# Install ALL dependencies and fix packaging
RUN poetry config virtualenvs.create false \
  && poetry install --no-interaction --no-ansi \
  && pip install --force-reinstall packaging==25.0

# Set environment variables
ENV PYTHONUNBUFFERED=1
# Disable virtualenv creation via environment variable
ENV POETRY_VIRTUALENVS_CREATE=false

# Handle tiktoken
ENV TIKTOKEN_CACHE_DIR=/tiktoken
RUN mkdir /tiktoken
ADD --chmod=644 https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken /tiktoken/9b5ad71b2ce5302211f9c61530b329a4922fc6a4

# CRITICAL: Give ownership to UID 1000 BEFORE switching user
RUN chown -R 1000:1000 /code /tiktoken

# Run as unprivileged user
USER 1000

CMD ["sh", "-c", "./run.sh"]