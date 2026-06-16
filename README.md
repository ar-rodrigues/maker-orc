# Marker en RunPod Serverless

Worker serverless que expone [Marker](https://github.com/datalab-to/marker) para convertir PDFs a markdown, JSON, HTML o chunks.

## Requisitos en RunPod

| Configuración | Recomendación |
|---|---|
| GPU | 16 GB+ VRAM (RTX 4090, A4000, L4, etc.) |
| Container disk | 20 GB+ (modelos ~3–5 GB) |
| Execution timeout | 300 s o más para PDFs largos |
| Idle timeout | 5–30 s según tu carga |

Marker usa ~3.5 GB VRAM en promedio por worker.

## Despliegue rápido

### 1. Construir y publicar la imagen

```bash
docker build -t tu-usuario/marker-runpod:latest .
docker login
docker push tu-usuario/marker-runpod:latest
```

### 2. Crear endpoint en RunPod

1. [RunPod Console](https://www.runpod.io/console/serverless) → **New Endpoint**
2. **Container Image**: `tu-usuario/marker-runpod:latest`
3. **GPU**: 16 GB+
4. **Container Disk**: 20 GB
5. Variables de entorno (opcional):
   - `TORCH_DEVICE=cuda`

### 3. Probar localmente (antes de desplegar)

```bash
pip install runpod marker-pdf
export RUNPOD_API_KEY=tu_clave  # solo para test_client.py
runpod handler handler.py --test_input test_input.json
```

### 4. Llamar al endpoint

```bash
python scripts/test_client.py documento.pdf TU_ENDPOINT_ID TU_API_KEY
```

O con `curl` (sincrónico):

```bash
curl -X POST "https://api.runpod.ai/v2/TU_ENDPOINT_ID/runsync" \
  -H "Authorization: Bearer TU_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"pdf_url":"https://arxiv.org/pdf/2101.03961.pdf","page_range":"0-1"}}'
```

## Formato de entrada

```json
{
  "input": {
    "pdf_base64": "<base64 del PDF>",
    "filename": "documento.pdf",
    "output_format": "markdown",
    "page_range": "0,5-10",
    "force_ocr": false,
    "paginate_output": false
  }
}
```

Alternativa: usar `"pdf_url"` en lugar de `pdf_base64` (URL pública).

## Formato de salida

```json
{
  "status": "success",
  "filename": "documento.pdf",
  "format": "markdown",
  "output": "# Contenido convertido...",
  "images": { "nombre.png": "<base64>" },
  "metadata": { "page_stats": [], "table_of_contents": [] }
}
```

## Licencia y uso comercial

Marker es GPL-3.0 y los pesos del modelo tienen restricciones de licencia. Revisa [datalab-to/marker](https://github.com/datalab-to/marker) antes de uso comercial.

## Despliegue desde GitHub

También puedes conectar este repositorio en RunPod (Settings → GitHub) y desplegar indicando `Dockerfile` como ruta del Dockerfile.
