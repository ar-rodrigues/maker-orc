FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TORCH_DEVICE=cuda
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

RUN mkdir -p /app/.cache/huggingface

COPY requirements.txt .
# marker-pdf instala torch 2.7; el image base trae torch 2.4 + torchvision viejo.
# Hay que limpiar y reinstalar torchvision compatible.
RUN pip uninstall -y transformers torch torchvision 2>/dev/null || true \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir torchvision --index-url https://download.pytorch.org/whl/cu124 \
    && python -c "import torch, torchvision; from transformers import PreTrainedModel; print('deps ok', torch.__version__, torchvision.__version__)"

COPY handler.py .

CMD ["python", "-u", "handler.py"]
