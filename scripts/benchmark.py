#!/usr/bin/env python3
"""Benchmark de conversión PDF → markdown en el endpoint RunPod."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

import requests

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
# RunPod /run body limit ~10 MiB; base64 agrega ~33%.
MAX_BASE64_BYTES = 9 * 1024 * 1024


def load_env_local(root: Path) -> None:
    env_file = root / ".env.local"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def upload_temp_url(pdf_path: Path) -> str:
    """Sube PDF temporalmente para pdf_url (archivos >7 MB no caben en base64)."""
    print("  subiendo a catbox.moe para pdf_url...", flush=True)
    with pdf_path.open("rb") as f:
        response = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (pdf_path.name, f, "application/pdf")},
            timeout=300,
        )
    response.raise_for_status()
    url = response.text.strip()
    if not url.startswith("http"):
        raise RuntimeError(f"URL temporal inválida: {url[:120]}")
    return url


def build_input(pdf_path: Path, page_range: str | None = None, force_ocr: bool = False) -> dict:
    size = pdf_path.stat().st_size
    estimated_b64 = int(size * 4 / 3)
    payload: dict = {
        "filename": pdf_path.name,
        "output_format": "markdown",
        "include_images": False,
        "disable_image_extraction": True,
    }
    if page_range:
        payload["page_range"] = page_range
    if force_ocr:
        payload["force_ocr"] = True
    if estimated_b64 <= MAX_BASE64_BYTES:
        with pdf_path.open("rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
        payload["pdf_base64"] = pdf_base64
        return payload
    payload["pdf_url"] = upload_temp_url(pdf_path)
    return payload


def submit_job(
    endpoint_id: str, api_key: str, pdf_path: Path, page_range: str | None = None,
    force_ocr: bool = False,
) -> str:
    payload = {"input": build_input(pdf_path, page_range, force_ocr)}
    url = f"https://api.runpod.ai/v2/{endpoint_id}/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()["id"]


def poll_job(endpoint_id: str, api_key: str, job_id: str, poll_s: float = 5.0) -> dict:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    while True:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        if data.get("status") in TERMINAL:
            return data
        time.sleep(poll_s)


def benchmark_file(
    endpoint_id: str,
    api_key: str,
    pdf_path: Path,
    page_range: str | None = None,
    force_ocr: bool = False,
) -> dict:
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    print(f"\n→ {pdf_path.name} ({size_mb:.2f} MB)", flush=True)

    wall_start = time.perf_counter()
    job_id = submit_job(endpoint_id, api_key, pdf_path, page_range, force_ocr)
    print(f"  job {job_id} enviado", flush=True)
    result = poll_job(endpoint_id, api_key, job_id)
    wall_s = time.perf_counter() - wall_start

    output = result.get("output") or {}
    metadata = output.get("metadata") or {}
    page_stats = metadata.get("page_stats") or []
    pages = len(page_stats)

    row = {
        "archivo": pdf_path.name,
        "tamano_mb": round(size_mb, 2),
        "metodo_envio": "pdf_url" if size_mb * 1024 * 1024 * 4 / 3 > MAX_BASE64_BYTES else "pdf_base64",
        "page_range": page_range,
        "force_ocr": force_ocr,
        "estado": result.get("status"),
        "cola_ms": result.get("delayTime"),
        "ejecucion_ms": result.get("executionTime"),
        "total_s": round(wall_s, 1),
        "paginas": pages,
        "caracteres_md": len(output.get("output") or ""),
        "error": result.get("error") or output.get("error"),
    }

    if row["estado"] == "COMPLETED" and row["ejecucion_ms"] and pages:
        row["seg_por_pagina"] = round(row["ejecucion_ms"] / 1000 / pages, 2)

    print(
        f"  {row['estado']}: cola={row['cola_ms']}ms "
        f"ejec={row['ejecucion_ms']}ms total={row['total_s']}s "
        f"paginas={pages}",
        flush=True,
    )
    if row.get("error"):
        print(f"  error: {row['error']}", flush=True)
    return row


def print_table(rows: list[dict]) -> None:
    print("\n" + "=" * 90)
    print(f"{'Archivo':<45} {'MB':>6} {'Cola':>7} {'Ejec':>8} {'Total':>7} {'Pág':>5} {'s/pág':>6}")
    print("-" * 90)
    for r in rows:
        cola = f"{r['cola_ms']/1000:.1f}s" if r.get("cola_ms") else "—"
        ejec = f"{r['ejecucion_ms']/1000:.1f}s" if r.get("ejecucion_ms") else "—"
        spp = f"{r['seg_por_pagina']:.1f}" if r.get("seg_por_pagina") else "—"
        name = r["archivo"][:44]
        print(
            f"{name:<45} {r['tamano_mb']:>6.2f} {cola:>7} {ejec:>8} "
            f"{r['total_s']:>6.1f}s {r.get('paginas', 0):>5} {spp:>6}"
        )
    print("=" * 90)


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Marker en RunPod")
    parser.add_argument(
        "--dir",
        default="test-files",
        help="Carpeta con PDFs (no se despliega)",
    )
    parser.add_argument(
        "--output",
        default="benchmark-results.json",
        help="Archivo JSON con resultados",
    )
    parser.add_argument(
        "--page-range",
        default=None,
        help='Rango de páginas Marker, ej. "0-49" (útil para PDFs muy largos)',
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="Forzar OCR en todo el documento (PDFs escaneados o con texto basura)",
    )
    parser.add_argument(
        "--only",
        action="append",
        dest="only_files",
        metavar="NOMBRE.pdf",
        help="Procesar solo estos archivos (puede repetirse)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    load_env_local(root)

    endpoint_id = os.environ.get("ENDPOINT_ID")
    api_key = os.environ.get("API_KEY") or os.environ.get("RUNPOD_API_KEY")
    if not endpoint_id or not api_key:
        print("Falta ENDPOINT_ID y API_KEY en .env.local", file=sys.stderr)
        sys.exit(1)

    test_dir = root / args.dir
    pdfs = sorted(test_dir.glob("*.pdf"))
    if args.only_files:
        wanted = set(args.only_files)
        pdfs = [p for p in pdfs if p.name in wanted]
        missing = wanted - {p.name for p in pdfs}
        if missing:
            print(f"Archivos no encontrados: {', '.join(sorted(missing))}", file=sys.stderr)
            sys.exit(1)
    if not pdfs:
        print(f"No hay PDFs en {test_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Benchmark: {len(pdfs)} archivos → endpoint {endpoint_id}")
    if args.page_range:
        print(f"page_range={args.page_range}")
    if args.force_ocr:
        print("force_ocr=true")

    rows = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}]", end="")
        rows.append(
            benchmark_file(
                endpoint_id, api_key, pdf, args.page_range, args.force_ocr
            )
        )

    out_path = root / args.output
    out_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print_table(rows)
    print(f"\nResultados guardados en {out_path}")


if __name__ == "__main__":
    main()
