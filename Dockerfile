FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TORCH_DEVICE=cuda
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

RUN mkdir -p /app/.cache/huggingface

COPY requirements.txt .
# El image base trae torch/torchvision/torchaudio desemparejados.
# Se eliminan y se instala todo en UNA resolución con torch+torchvision fijados
# y compatibles (torch 2.7.0 <-> torchvision 0.22.0) para evitar el error
# "operator torchvision::nms does not exist".
RUN pip uninstall -y torch torchvision torchaudio transformers triton 2>/dev/null || true \
    && pip install --no-cache-dir -r requirements.txt \
    && python -c "import torch, torchvision; from transformers import PreTrainedModel; print('deps ok', torch.__version__, torchvision.__version__)"

COPY handler.py .

CMD ["python", "-u", "handler.py"]
