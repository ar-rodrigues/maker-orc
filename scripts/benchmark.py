#!/usr/bin/env python3
"""Benchmark PDF → markdown simulando producción: una página por job en paralelo."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def get_page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"No se pudo leer {pdf_path.name} con pdfinfo "
            f"(instala poppler-utils): {result.stderr.strip()}"
        )
    for line in result.stdout.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise RuntimeError(f"pdfinfo no reportó páginas para {pdf_path.name}")


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


def build_base_input(
    pdf_path: Path,
    force_ocr: bool = False,
    use_llm: bool = False,
) -> tuple[dict, str]:
    """Payload compartido por todos los jobs de páginas de un mismo archivo."""
    size = pdf_path.stat().st_size
    estimated_b64 = int(size * 4 / 3)
    payload: dict = {
        "filename": pdf_path.name,
        "output_format": "markdown",
        "include_images": False,
        "disable_image_extraction": True,
    }
    if force_ocr:
        payload["force_ocr"] = True
    if use_llm:
        payload["use_llm"] = True

    if estimated_b64 <= MAX_BASE64_BYTES:
        with pdf_path.open("rb") as f:
            pdf_base64 = base64.b64encode(f.read()).decode("utf-8")
        payload["pdf_base64"] = pdf_base64
        metodo = "pdf_base64"
    else:
        payload["pdf_url"] = upload_temp_url(pdf_path)
        metodo = "pdf_url"
    return payload, metodo


def submit_job(endpoint_id: str, api_key: str, job_input: dict) -> str:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = requests.post(
        url, headers=headers, json={"input": job_input}, timeout=120
    )
    response.raise_for_status()
    return response.json()["id"]


def poll_job(endpoint_id: str, api_key: str, job_id: str, poll_s: float = 3.0) -> dict:
    url = f"https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    while True:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        data = response.json()
        if data.get("status") in TERMINAL:
            return data
        time.sleep(poll_s)


def process_page(
    endpoint_id: str,
    api_key: str,
    base_input: dict,
    page_num: int,
) -> dict:
    job_input = {**base_input, "page_range": str(page_num)}
    wall_start = time.perf_counter()
    job_id = submit_job(endpoint_id, api_key, job_input)
    result = poll_job(endpoint_id, api_key, job_id)
    wall_s = time.perf_counter() - wall_start

    output = result.get("output") or {}
    metadata = output.get("metadata") or {}
    page_stats = metadata.get("page_stats") or []

    return {
        "pagina": page_num,
        "job_id": job_id,
        "estado": result.get("status"),
        "cola_ms": result.get("delayTime"),
        "ejecucion_ms": result.get("executionTime"),
        "total_s": round(wall_s, 2),
        "paginas_reportadas": len(page_stats),
        "caracteres_md": len(output.get("output") or ""),
        "error": result.get("error") or output.get("error"),
    }


def benchmark_file_parallel(
    endpoint_id: str,
    api_key: str,
    pdf_path: Path,
    *,
    concurrency: int,
    goal_seconds: float,
    force_ocr: bool = False,
    use_llm: bool = False,
    max_pages: int | None = None,
) -> dict:
    size_mb = pdf_path.stat().st_size / (1024 * 1024)
    total_pages = get_page_count(pdf_path)
    pages_to_run = (
        min(total_pages, max_pages) if max_pages is not None else total_pages
    )

    print(
        f"\n→ {pdf_path.name} ({size_mb:.2f} MB, {total_pages} págs, "
        f"procesando {pages_to_run} en paralelo x{concurrency})",
        flush=True,
    )

    base_input, metodo = build_base_input(pdf_path, force_ocr, use_llm)
    page_nums = list(range(pages_to_run))

    wall_start = time.perf_counter()
    page_results: list[dict] = []
    done = 0

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                process_page, endpoint_id, api_key, base_input, page_num
            ): page_num
            for page_num in page_nums
        }
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = {
                    "pagina": page_num,
                    "estado": "FAILED",
                    "error": str(exc),
                }
            page_results.append(row)
            done += 1
            status = row.get("estado", "?")
            ejec = row.get("ejecucion_ms")
            ejec_s = f"{ejec / 1000:.1f}s" if ejec else "—"
            print(
                f"  [{done}/{pages_to_run}] pág {page_num}: {status} ejec={ejec_s}",
                flush=True,
            )
            if row.get("error"):
                print(f"    error: {row['error']}", flush=True)

    wall_s = time.perf_counter() - wall_start
    page_results.sort(key=lambda r: r["pagina"])

    ok = [r for r in page_results if r.get("estado") == "COMPLETED"]
    failed = [r for r in page_results if r.get("estado") != "COMPLETED"]
    exec_times = [
        r["ejecucion_ms"] / 1000
        for r in ok
        if r.get("ejecucion_ms")
    ]

    waves_done = max(1, (pages_to_run + concurrency - 1) // concurrency)
    waves_full = (total_pages + concurrency - 1) // concurrency
    if pages_to_run < total_pages:
        projected_wall_s = round((wall_s / waves_done) * waves_full, 1)
    else:
        projected_wall_s = round(wall_s, 1)

    summary = {
        "archivo": pdf_path.name,
        "tamano_mb": round(size_mb, 2),
        "metodo_envio": metodo,
        "modo": "paginas_paralelas",
        "concurrencia": concurrency,
        "force_ocr": force_ocr,
        "use_llm": use_llm,
        "paginas_totales": total_pages,
        "paginas_procesadas": pages_to_run,
        "paginas_ok": len(ok),
        "paginas_fallo": len(failed),
        "tiempo_pared_s": round(wall_s, 1),
        "tiempo_proyectado_archivo_s": projected_wall_s,
        "meta_segundos": goal_seconds,
        "cumple_meta": projected_wall_s <= goal_seconds and not failed,
        "cola_max_ms": max((r.get("cola_ms") or 0) for r in page_results) or None,
        "ejecucion_suma_s": round(sum(exec_times), 1) if exec_times else None,
        "ejecucion_max_s": round(max(exec_times), 2) if exec_times else None,
        "ejecucion_promedio_s": round(sum(exec_times) / len(exec_times), 2)
        if exec_times
        else None,
        "paginas": page_results,
    }

    meta = "SÍ" if summary["cumple_meta"] else "NO"
    print(
        f"  RESUMEN: pared={summary['tiempo_pared_s']}s "
        f"proy={summary['tiempo_proyectado_archivo_s']}s "
        f"ok={len(ok)}/{pages_to_run} meta {goal_seconds}s={meta}",
        flush=True,
    )
    return summary


def print_table(rows: list[dict]) -> None:
    print("\n" + "=" * 100)
    print(
        f"{'Archivo':<42} {'Pág':>5} {'Par':>4} {'Pared':>7} "
        f"{'Proy':>7} {'Meta':>5} {'OK':>7} {'s/pág':>6}"
    )
    print("-" * 100)
    for r in rows:
        name = r["archivo"][:41]
        pared = f"{r['tiempo_pared_s']:.0f}s"
        proy = f"{r['tiempo_proyectado_archivo_s']:.0f}s"
        meta = "SÍ" if r.get("cumple_meta") else "NO"
        ok = f"{r['paginas_ok']}/{r['paginas_procesadas']}"
        spp = (
            f"{r['ejecucion_promedio_s']:.1f}"
            if r.get("ejecucion_promedio_s")
            else "—"
        )
        print(
            f"{name:<42} {r['paginas_totales']:>5} {r['concurrencia']:>4} "
            f"{pared:>7} {proy:>7} {meta:>5} {ok:>7} {spp:>6}"
        )
    print("=" * 100)
    print(
        "Pared = tiempo real del benchmark. Proy = estimado para el archivo completo "
        "(igual a pared si se procesaron todas las páginas)."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark Marker en RunPod (una página por job, en paralelo)"
    )
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
        "--concurrency",
        type=int,
        default=10,
        help="Jobs de página en paralelo (alinear con max workers del endpoint)",
    )
    parser.add_argument(
        "--goal-seconds",
        type=float,
        default=300,
        help="Meta de tiempo para procesar el archivo completo",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Procesar solo las primeras N páginas (útil para pruebas rápidas)",
    )
    parser.add_argument(
        "--force-ocr",
        action="store_true",
        help="Forzar OCR en todo el documento (PDFs escaneados)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Activar post-proceso Gemini (requiere GOOGLE_API_KEY en RunPod)",
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
            print(
                f"Archivos no encontrados: {', '.join(sorted(missing))}",
                file=sys.stderr,
            )
            sys.exit(1)
    if not pdfs:
        print(f"No hay PDFs en {test_dir}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Benchmark paralelo: {len(pdfs)} archivos → endpoint {endpoint_id} "
        f"(concurrencia={args.concurrency}, meta={args.goal_seconds}s)"
    )
    if args.force_ocr:
        print("force_ocr=true")
    if args.use_llm:
        print("use_llm=true")
    if args.max_pages is not None:
        print(f"max_pages={args.max_pages}")

    rows = []
    for i, pdf in enumerate(pdfs, 1):
        print(f"\n[{i}/{len(pdfs)}]", end="")
        rows.append(
            benchmark_file_parallel(
                endpoint_id,
                api_key,
                pdf,
                concurrency=args.concurrency,
                goal_seconds=args.goal_seconds,
                force_ocr=args.force_ocr,
                use_llm=args.use_llm,
                max_pages=args.max_pages,
            )
        )

    out_path = root / args.output
    out_path.write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print_table(rows)
    print(f"\nResultados guardados en {out_path}")


if __name__ == "__main__":
    main()
