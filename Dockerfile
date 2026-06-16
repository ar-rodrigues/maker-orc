FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TORCH_DEVICE=cuda
ENV HF_HOME=/runpod-volume/huggingface
ENV TRANSFORMERS_CACHE=/runpod-volume/huggingface

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Los modelos se cargan al arrancar el worker (handler.py), no en build.
# Evita timeouts en el build de GitHub (CPU, límite ~30 min).

COPY handler.py .

CMD ["python", "-u", "handler.py"]
