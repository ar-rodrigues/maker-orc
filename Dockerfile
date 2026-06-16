FROM runpod/pytorch:1.0.6-cu1281-torch271-ubuntu2204

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV TORCH_DEVICE=cuda
ENV HF_HOME=/app/.cache/huggingface
ENV TRANSFORMERS_CACHE=/app/.cache/huggingface
# Paralelismo CPU para pdftext (ajustar según vCPU del pod; 4 suele ir bien en 24GB GPU).
ENV PDFTEXT_CPU_WORKERS=4
ENV OMP_NUM_THREADS=4
ENV OPENBLAS_NUM_THREADS=4
# Opcional: descomentar si la VRAM lo permite y quieres más velocidad en OCR.
# ENV RECOGNITION_MODEL_QUANTIZE=true
# ENV COMPILE_ALL=true

RUN mkdir -p /app/.cache/huggingface

COPY requirements.txt constraints.txt ./
# Usar el torch 2.7.1 + CUDA del image base de RunPod (kernels GPU correctos).
# Solo reemplazar transformers y instalar marker sin tocar torch.
RUN pip uninstall -y transformers 2>/dev/null || true \
    && pip install --no-cache-dir -c constraints.txt -r requirements.txt \
    && python -c "import torch, torchvision; from transformers import PreTrainedModel; assert torch.version.cuda; print('deps ok', torch.__version__, torchvision.__version__, torch.version.cuda)"

COPY handler.py .

CMD ["python", "-u", "handler.py"]
