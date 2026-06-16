"""
Worker RunPod Serverless para convertir documentos con Marker.

Entrada esperada (job["input"]):
  - pdf_base64: contenido del PDF codificado en base64 (requerido si no hay pdf_url)
  - pdf_url: URL pública del PDF (alternativa a pdf_base64)
  - filename: nombre del archivo (opcional, default: document.pdf)
  - output_format: markdown | json | html | chunks (default: markdown)
  - page_range: rango de páginas, ej. "0,5-10,20"
  - force_ocr: bool — OCR en todo el documento (recomendado para escaneos con capa de texto basura)
  - strip_existing_ocr: bool — quita OCR embebido y re-OCR con surya
  - include_images: bool (default: false) — incluir imágenes extraídas en base64 en la respuesta
  - disable_image_extraction: bool — no extraer imágenes (más rápido; anula include_images)
  - paginate_output: bool (default: false)
  - use_llm: bool — post-proceso con Gemini (requiere GOOGLE_API_KEY en el worker)
  - llm_service: str (opcional) — clase LLM de Marker; default GoogleGeminiService
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import threading
import traceback
import urllib.request
from typing import Any

import runpod

_models = None
_models_lock = threading.Lock()

# RunPod limita el body de /run a ~10 MiB; archivos mayores deben usar pdf_url.
PDF_URL_TIMEOUT_S = int(os.environ.get("PDF_URL_TIMEOUT_S", "300"))
PDFTEXT_CPU_WORKERS = int(os.environ.get("PDFTEXT_CPU_WORKERS", "4"))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_use_llm(job_input: dict[str, Any]) -> bool:
    if "use_llm" in job_input:
        return bool(job_input["use_llm"])
    return _env_bool("USE_LLM", False)


def _get_models():
    """Carga modelos bajo demanda en el primer job."""
    global _models
    if _models is None:
        with _models_lock:
            if _models is None:
                from marker.models import create_model_dict

                print("Cargando modelos de Marker...")
                _models = create_model_dict()
                print("Modelos de Marker listos.")
    return _models


def _decode_pdf(job_input: dict[str, Any]) -> tuple[str, str]:
    """Devuelve (ruta temporal, nombre de archivo)."""
    filename = job_input.get("filename", "document.pdf")
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"

    pdf_base64 = job_input.get("pdf_base64")
    pdf_url = job_input.get("pdf_url")

    if pdf_base64:
        pdf_bytes = base64.b64decode(pdf_base64)
    elif pdf_url:
        request = urllib.request.Request(
            pdf_url,
            headers={"User-Agent": "maker-orc/1.0 (RunPod Marker worker)"},
        )
        with urllib.request.urlopen(request, timeout=PDF_URL_TIMEOUT_S) as response:
            pdf_bytes = response.read()
    else:
        raise ValueError("Se requiere 'pdf_base64' o 'pdf_url' en el input.")

    suffix = os.path.splitext(filename)[1] or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(pdf_bytes)
    tmp.close()
    return tmp.name, filename


def _encode_images(images: dict) -> dict[str, str]:
    from marker.settings import settings

    encoded: dict[str, str] = {}
    for key, image in images.items():
        stream = io.BytesIO()
        image.save(stream, format=settings.OUTPUT_IMAGE_FORMAT)
        encoded[key] = base64.b64encode(stream.getvalue()).decode(settings.OUTPUT_ENCODING)
    return encoded


def handler(job: dict) -> dict:
    from marker.config.parser import ConfigParser
    from marker.converters.pdf import PdfConverter
    from marker.output import text_from_rendered

    job_input = job.get("input", {})
    tmp_path: str | None = None

    try:
        output_format = job_input.get("output_format", "markdown")
        if output_format not in ("markdown", "json", "html", "chunks"):
            raise ValueError(
                "output_format debe ser: markdown, json, html o chunks"
            )

        tmp_path, filename = _decode_pdf(job_input)

        include_images = bool(job_input.get("include_images", False))
        disable_image_extraction = bool(
            job_input.get("disable_image_extraction", not include_images)
        )
        use_llm = _resolve_use_llm(job_input)

        if use_llm and not os.environ.get("GOOGLE_API_KEY", "").strip():
            raise ValueError(
                "use_llm está activo pero falta GOOGLE_API_KEY en las variables "
                "de entorno del worker (RunPod → Environment Variables)."
            )

        options = {
            "filepath": tmp_path,
            "output_format": output_format,
            "page_range": job_input.get("page_range"),
            "force_ocr": bool(job_input.get("force_ocr", False)),
            "strip_existing_ocr": bool(job_input.get("strip_existing_ocr", False)),
            "paginate_output": bool(job_input.get("paginate_output", False)),
            "disable_image_extraction": disable_image_extraction,
            "use_llm": use_llm,
        }
        if job_input.get("llm_service"):
            options["llm_service"] = job_input["llm_service"]

        if use_llm:
            print("Modo LLM activo (Gemini).", flush=True)

        config_parser = ConfigParser(options)
        config_dict = config_parser.generate_config_dict()
        config_dict["pdftext_workers"] = int(
            job_input.get("pdftext_workers", PDFTEXT_CPU_WORKERS)
        )
        config_dict["disable_tqdm"] = True

        converter = PdfConverter(
            config=config_dict,
            artifact_dict=_get_models(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
            llm_service=config_parser.get_llm_service(),
        )

        rendered = converter(tmp_path)
        text, _, images = text_from_rendered(rendered)

        result = {
            "status": "success",
            "filename": filename,
            "format": output_format,
            "use_llm": use_llm,
            "output": text,
            "metadata": rendered.metadata,
        }
        if include_images and not disable_image_extraction:
            result["images"] = _encode_images(images)
        return result

    except Exception as exc:
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(exc),
        }

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


print("Iniciando worker maker-orc...")
runpod.serverless.start({"handler": handler})
