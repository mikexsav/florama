FROM python:3.12-slim
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
ENV DB_PATH=/data/florama.sqlite3 DATA_DIR=/data OMP_NUM_THREADS=2
EXPOSE 8000
CMD ["gunicorn","--workers","2","--threads","2","--bind","0.0.0.0:8000","app:create_app()"]
