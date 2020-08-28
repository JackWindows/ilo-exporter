from python:3.8

COPY requirements.txt .
RUN pip install -r requirements.txt

ENV PYTHONPATH=/app
WORKDIR /app/ilo_exporter
EXPOSE 9116

COPY ilo_exporter /app/ilo_exporter

CMD main.py
