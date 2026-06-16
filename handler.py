"""
Worker RunPod Serverless para convertir documentos con Marker.

Entrada esperada (job["input"]):
  - pdf_base64: contenido del PDF codificado en base64 (requerido si no hay pdf_url)
  - pdf_url: URL pública del PDF (alternativa a pdf_base64)
  - filename: nombre del archivo (opcional, default: document.pdf)
  - output_format: markdown | json | html | chunks (default: markdown)
  - page_range: rango de páginas, ej. "0,5-10,20"
  - force_ocr: bool (default: false)
  - paginate_output: bool (default: false)
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
from marker.config.parser import ConfigParser
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered
from marker.settings import settings

_models = None
_models_lock = threading.Lock()


def _get_models():
    """Carga modelos bajo demanda para que el worker registre ping antes."""
    global _models
    if _models is None:
        with _models_lock:
            if _models is None:
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
        with urllib.request.urlopen(pdf_url, timeout=120) as response:
            pdf_bytes = response.read()
    else:
        raise ValueError("Se requiere 'pdf_base64' o 'pdf_url' en el input.")

    suffix = os.path.splitext(filename)[1] or ".pdf"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(pdf_bytes)
    tmp.close()
    return tmp.name, filename


def _encode_images(images: dict) -> dict[str, str]:
    encoded: dict[str, str] = {}
    for key, image in images.items():
        stream = io.BytesIO()
        image.save(stream, format=settings.OUTPUT_IMAGE_FORMAT)
        encoded[key] = base64.b64encode(stream.getvalue()).decode(settings.OUTPUT_ENCODING)
    return encoded


def handler(job: dict) -> dict:
    job_input = job.get("input", {})
    tmp_path: str | None = None

    try:
        output_format = job_input.get("output_format", "markdown")
        if output_format not in ("markdown", "json", "html", "chunks"):
            raise ValueError(
                "output_format debe ser: markdown, json, html o chunks"
            )

        tmp_path, filename = _decode_pdf(job_input)

        options = {
            "filepath": tmp_path,
            "output_format": output_format,
            "page_range": job_input.get("page_range"),
            "force_ocr": bool(job_input.get("force_ocr", False)),
            "paginate_output": bool(job_input.get("paginate_output", False)),
        }

        config_parser = ConfigParser(options)
        config_dict = config_parser.generate_config_dict()
        config_dict["pdftext_workers"] = 1

        converter = PdfConverter(
            config=config_dict,
            artifact_dict=_get_models(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
            llm_service=config_parser.get_llm_service(),
        )

        rendered = converter(tmp_path)
        text, _, images = text_from_rendered(rendered)

        return {
            "status": "success",
            "filename": filename,
            "format": output_format,
            "output": text,
            "images": _encode_images(images),
            "metadata": rendered.metadata,
        }

    except Exception as exc:
        traceback.print_exc()
        return {
            "status": "error",
            "error": str(exc),
        }

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


runpod.serverless.start({"handler": handler})
