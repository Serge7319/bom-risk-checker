FROM python:3.11.9-slim

WORKDIR /app
COPY apps/api/requirements.txt /app/apps/api/requirements.txt
RUN pip install --no-cache-dir -r /app/apps/api/requirements.txt

COPY apps /app/apps
COPY src /app/src
COPY integrations /app/integrations
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8787
EXPOSE 8787
CMD ["bash", "apps/api/start.sh"]
