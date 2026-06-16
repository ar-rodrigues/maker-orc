#!/usr/bin/env python3
"""Cliente de prueba para el endpoint RunPod Serverless de Marker."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Probar endpoint Marker en RunPod")
    parser.add_argument("pdf_path", help="Ruta al archivo PDF local")
    parser.add_argument("endpoint_id", help="ID del endpoint RunPod (sin URL completa)")
    parser.add_argument("api_key", nargs="?", default=os.environ.get("RUNPOD_API_KEY"))
    parser.add_argument(
        "--output-format",
        default="markdown",
        choices=["markdown", "json", "html", "chunks"],
    )
    parser.add_argument("--page-range", default=None)
    parser.add_argument("--force-ocr", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        print("Error: proporciona RUNPOD_API_KEY o el api_key como argumento.", file=sys.stderr)
        sys.exit(1)

    with open(args.pdf_path, "rb") as f:
        pdf_base64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "input": {
            "pdf_base64": pdf_base64,
            "filename": os.path.basename(args.pdf_path),
            "output_format": args.output_format,
        }
    }
    if args.page_range:
        payload["input"]["page_range"] = args.page_range
    if args.force_ocr:
        payload["input"]["force_ocr"] = True

    url = f"https://api.runpod.ai/v2/{args.endpoint_id}/runsync"
    headers = {
        "Authorization": f"Bearer {args.api_key}",
        "Content-Type": "application/json",
    }

    print(f"Enviando solicitud a {url}...")
    response = requests.post(url, headers=headers, json=payload, timeout=600)
    response.raise_for_status()
    result = response.json()

    print(json.dumps(result, indent=2, ensure_ascii=False)[:4000])

    output = result.get("output") or result.get("id")
    if isinstance(output, dict) and output.get("status") == "success":
        out_path = f"salida.{args.output_format if args.output_format != 'chunks' else 'json'}"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output.get("output", ""))
        print(f"\nSalida guardada en {out_path}")


if __name__ == "__main__":
    main()
