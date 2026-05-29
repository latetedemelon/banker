FROM python:3.9-alpine

WORKDIR /app
ENV PYTHONPATH "/app:/app/lib"
ENV ENV production

COPY Pipfile.lock .
COPY Pipfile .

RUN pip install pipenv \
  && pipenv requirements > requirements.txt \
  && pip install -r requirements.txt

USER nobody

COPY . .

ENTRYPOINT ["python", "main.py"]
