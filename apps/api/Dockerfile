FROM python:3.12-slim
ARG KIPNERTER_RELEASE_SHA
ENV KIPNERTER_RELEASE_SHA=${KIPNERTER_RELEASE_SHA}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
