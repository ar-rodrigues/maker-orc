FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TORCH_DEVICE=cuda
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface

RUN mkdir -p /app/.cache/huggingface

COPY requirements.txt .
# torch/torchvision deben venir del índice CUDA de PyTorch, no de PyPI (CPU o sin kernels GPU).
RUN pip uninstall -y torch torchvision torchaudio transformers triton 2>/dev/null || true \
    && pip install --no-cache-dir torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu126 \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall --no-deps torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu126 \
    && python -c "import torch, torchvision; from transformers import PreTrainedModel; assert torch.version.cuda; print('deps ok', torch.__version__, torchvision.__version__, 'cuda', torch.version.cuda)"

COPY handler.py .

CMD ["python", "-u", "handler.py"]
