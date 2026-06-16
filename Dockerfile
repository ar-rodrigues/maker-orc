FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TORCH_DEVICE=cuda
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

RUN mkdir -p /app/.cache/huggingface

COPY requirements.txt .
# Instalar torch+torchvision emparejados ANTES de marker-pdf para evitar conflictos.
RUN pip uninstall -y transformers torch torchvision triton 2>/dev/null || true \
    && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cu124 \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import torch, torchvision; from transformers import PreTrainedModel; print('deps ok', torch.__version__, torchvision.__version__)"

COPY handler.py .

CMD ["python", "-u", "handler.py"]
