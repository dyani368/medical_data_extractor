FROM python:3.12-slim

WORKDIR /app

# The API uses CPU inference; avoid pulling CUDA libraries into the image.
RUN pip install --no-cache-dir --no-deps torch==2.7.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

RUN python -m spacy download en_core_web_sm

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
