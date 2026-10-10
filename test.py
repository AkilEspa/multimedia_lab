#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas automáticas de la aplicación FastAPI de compresión multimedia.

No necesita requests ni pytest: utiliza únicamente la biblioteca estándar de Python.
La aplicación debe estar arrancada con: python -m uvicorn main:app --reload

Uso habitual:
    python test.py
    python test.py --folder "C:\\Users\\TU_USUARIO\\Desktop\\multimedia_test_files"
    python test.py --skip-video
"""

from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


EXPECTED_FILES = {
    "Imagenes": [
        "muestra.jpg", "muestra.png", "muestra.webp",
        "muestra.gif", "muestra.bmp",
    ],
    "Audio": [
        "muestra.mp3", "muestra.wav", "muestra.ogg",
        "muestra.flac", "muestra.aac", "muestra.m4a",
        "muestra.opus", "muestra.wma",
    ],
    "Video": [
        "muestra.mp4", "muestra.webm", "muestra.mov",
        "muestra.mkv", "muestra.avi",
    ],
    "Comprimidos": [
        "muestra.csv.gz", "muestra.tar.gz",
        "muestra.tar.bz2", "muestra.tar.xz",
    ],
    "Texto": ["texto_prueba.txt"],
}


class ApiFailure(Exception):
    """Error HTTP/API con un mensaje que puede mostrarse en el informe."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta pruebas automáticas contra la API de compresión multimedia."
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000",
        help="URL base de FastAPI (por defecto: http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--folder",
        default=None,
        help="Carpeta multimedia_test_files. Si se omite, se busca en ubicaciones habituales.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=240,
        help="Tiempo máximo en segundos por petición (por defecto: 240).",
    )
    parser.add_argument(
        "--skip-video",
        action="store_true",
        help="Omite las conversiones de vídeo para realizar una prueba más rápida.",
    )
    return parser.parse_args()


def find_sample_folder(explicit_folder: str | None) -> Path | None:
    if explicit_folder:
        candidate = Path(explicit_folder).expanduser().resolve()
        return candidate if candidate.is_dir() else None

    script_dir = Path(__file__).resolve().parent
    candidates = [
        Path.cwd() / "multimedia_test_files",
        script_dir / "multimedia_test_files",
        Path.home() / "Desktop" / "multimedia_test_files",
        Path.home() / "OneDrive" / "Desktop" / "multimedia_test_files",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def get_response(url: str, data: bytes | None = None,
                 headers: dict[str, str] | None = None,
                 timeout: int = 240) -> tuple[int, bytes, str]:
    request = Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers.get("Content-Type", "")
    except HTTPError as exc:
        body = exc.read()
        message = body.decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
            message = str(payload.get("detail", payload))
        except (json.JSONDecodeError, AttributeError):
            pass
        raise ApiFailure(f"HTTP {exc.code}: {message}") from exc
    except (URLError, TimeoutError) as exc:
        raise ApiFailure(str(getattr(exc, "reason", exc))) from exc


def post_form(base_url: str, endpoint: str, fields: dict[str, str], timeout: int) -> dict[str, Any]:
    body = urlencode(fields).encode("utf-8")
    status, raw, _ = get_response(
        base_url + endpoint,
        body,
        {"Content-Type": "application/x-www-form-urlencoded"},
        timeout,
    )
    try:
        result = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiFailure(f"La API no devolvió JSON válido (HTTP {status}).") from exc
    if not isinstance(result, dict):
        raise ApiFailure("La API devolvió una respuesta JSON inesperada.")
    return result


def guess_content_type(path: Path, category: str) -> str:
    ext = path.name.lower()
    if category == "Imagenes":
        return {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp",
            ".gif": "image/gif", ".bmp": "image/bmp",
        }.get(path.suffix.lower(), "application/octet-stream")
    if category == "Audio":
        return {
            ".mp3": "audio/mpeg", ".wav": "audio/wav",
            ".ogg": "audio/ogg", ".flac": "audio/flac",
            ".aac": "audio/aac", ".m4a": "audio/mp4",
            ".opus": "audio/ogg", ".wma": "audio/x-ms-wma",
        }.get(path.suffix.lower(), "application/octet-stream")
    if category == "Video":
        return {
            ".mp4": "video/mp4", ".webm": "video/webm",
            ".mov": "video/quicktime", ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
        }.get(path.suffix.lower(), "application/octet-stream")
    if ext.endswith(".gz"):
        return "application/gzip"
    if ext.endswith(".bz2"):
        return "application/x-bzip2"
    if ext.endswith(".xz"):
        return "application/x-xz"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or ("text/plain" if category == "Texto" else "application/octet-stream")


def upload_file(base_url: str, path: Path, category: str,
                remote_filename: str, timeout: int) -> dict[str, Any]:
    boundary = "----MultimediaTest" + uuid.uuid4().hex
    mime_type = guess_content_type(path, category)
    file_bytes = path.read_bytes()
    safe_name = remote_filename.replace('"', "_").replace("\r", "_").replace("\n", "_")

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("ascii")

    status, raw, _ = get_response(
        base_url + "/upload",
        body,
        {"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout,
    )
    try:
        result = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ApiFailure(f"/upload devolvió una respuesta no JSON (HTTP {status}).") from exc
    if not isinstance(result, dict) or "filename" not in result:
        raise ApiFailure(f"Respuesta inesperada de /upload: {result}")
    return result


def verify_download(base_url: str, filename: str, timeout: int) -> tuple[bool, str]:
    url = base_url + "/download/" + quote(filename, safe="")
    try:
        status, content, _ = get_response(url, timeout=timeout)
        if status == 200 and len(content) > 0:
            return True, f"descarga verificada ({len(content)} bytes)"
        return False, "descarga vacía o con estado inesperado"
    except ApiFailure as exc:
        return False, f"no se pudo descargar: {exc}"


def add_result(results: list[dict[str, str]], category: str, filename: str,
               test_name: str, status: str, detail: str, duration: float = 0.0) -> None:
    results.append({
        "categoria": category,
        "archivo": filename,
        "prueba": test_name,
        "resultado": status,
        "duracion_segundos": f"{duration:.2f}",
        "detalle": detail.replace("\n", " ").strip(),
    })
    color = {"OK": "\033[92m", "ERROR": "\033[91m", "OMITIDA": "\033[93m"}.get(status, "")
    reset = "\033[0m" if color else ""
    print(f"[{color}{status}{reset}] {category}/{filename} — {test_name}: {detail} ({duration:.1f} s)")


def compress_and_check(base_url: str, original_filename: str, category: str,
                       uploaded_type: str, mode: str, algorithm: str,
                       timeout: int, results: list[dict[str, str]]) -> None:
    start = time.monotonic()
    test_name = f"compresión {mode}/{algorithm}"
    try:
        payload = post_form(base_url, "/compress", {
            "filename": original_filename,
            "file_type": uploaded_type,
            "mode": mode,
            "algorithm": algorithm,
        }, timeout)

        required = {"output_filename", "original_size", "compressed_size", "report_filename"}
        missing = sorted(required - payload.keys())
        if missing:
            raise ApiFailure(f"Faltan campos en la respuesta: {', '.join(missing)}")

        output_name = str(payload["output_filename"])
        report_name = str(payload["report_filename"])
        download_ok, download_detail = verify_download(base_url, output_name, timeout)
        if not download_ok:
            raise ApiFailure("No se pudo descargar el resultado: " + download_detail)

        report_ok, report_detail = verify_download(base_url, report_name, timeout)
        if not report_ok:
            raise ApiFailure("No se pudo descargar el informe: " + report_detail)

        original_size = int(payload["original_size"])
        output_size = int(payload["compressed_size"])
        reduction = payload.get("reduction_percent")
        skipped = bool(payload.get("skipped", False))
        summary = (
            f"{original_size} → {output_size} bytes; "
            f"reducción={float(reduction):.1f}%" if reduction is not None
            else f"{original_size} → {output_size} bytes"
        )
        if skipped:
            summary += "; compresión descartada y original conservado"
        summary += f"; resultado e informe descargables; {report_detail}"

        add_result(results, category, original_filename, test_name, "OK", summary,
                   time.monotonic() - start)
    except Exception as exc:
        add_result(results, category, original_filename, test_name, "ERROR", str(exc),
                   time.monotonic() - start)


def decompress_and_check(base_url: str, original_filename: str, category: str,
                          timeout: int, results: list[dict[str, str]]) -> None:
    start = time.monotonic()
    try:
        payload = post_form(base_url, "/decompress-gzip", {
            "filename": original_filename,
        }, timeout)
        output_name = str(payload["output_filename"])
        size = int(payload.get("decompressed_size", 0))
        if size <= 0:
            raise ApiFailure("La API informó un resultado descomprimido vacío.")
        ok, detail = verify_download(base_url, output_name, timeout)
        if not ok:
            raise ApiFailure("No se pudo descargar el archivo descomprimido: " + detail)
        add_result(results, category, original_filename, "descompresión GZIP", "OK",
                   f"generado {output_name} ({size} bytes); {detail}",
                   time.monotonic() - start)
    except Exception as exc:
        add_result(results, category, original_filename, "descompresión GZIP", "ERROR",
                   str(exc), time.monotonic() - start)


def main() -> int:
    args = parse_args()
    base_url = args.url.rstrip("/")
    root = find_sample_folder(args.folder)
    if root is None:
        print("ERROR: no se encuentra la carpeta multimedia_test_files.")
        print("Indica su ubicación con --folder, por ejemplo:")
        print('  python test.py --folder "C:\\Users\\TU_USUARIO\\Desktop\\multimedia_test_files"')
        return 2

    print(f"Carpeta de muestras: {root}")
    print(f"Aplicación: {base_url}")
    print("Comprobando que FastAPI esté arrancado...")
    try:
        status, _, _ = get_response(base_url + "/", timeout=min(args.timeout, 15))
        if status != 200:
            print(f"ERROR: la página principal respondió HTTP {status}.")
            return 2
    except ApiFailure as exc:
        print(f"ERROR: no se puede conectar con la aplicación: {exc}")
        print("Arranca la aplicación en otra consola con: python -m uvicorn main:app --reload")
        return 2

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:5]
    results: list[dict[str, str]] = []
    uploaded: dict[tuple[str, str], dict[str, Any]] = {}
    missing_files: list[str] = []

    # Cargar cada muestra una vez. El nombre remoto es único para evitar
    # colisiones entre salidas como muestra_lossless.webp.
    for category, names in EXPECTED_FILES.items():
        for name in names:
            if args.skip_video and category == "Video":
                continue
            local_path = root / category / name
            if not local_path.is_file():
                missing_files.append(f"{category}/{name}")
                add_result(results, category, name, "archivo de muestra", "OMITIDA",
                           "No se encontró el archivo local.")
                continue

            remote_name = f"autotest_{run_id}_{category}_{name}"
            try:
                data = upload_file(base_url, local_path, category, remote_name, args.timeout)
                uploaded[(category, name)] = {
                    "path": local_path,
                    "filename": str(data["filename"]),
                    "file_type": str(data.get("file_type", "")),
                }
                add_result(results, category, name, "subida", "OK",
                           f"detectado como tipo '{data.get('file_type', 'desconocido')}'")
            except Exception as exc:
                add_result(results, category, name, "subida", "ERROR", str(exc))

    # Imágenes: todos los ficheros pasan por WebP sin pérdida y por una
    # conversión con pérdida adecuada al formato de entrada.
    for name in EXPECTED_FILES["Imagenes"]:
        item = uploaded.get(("Imagenes", name))
        if not item:
            continue
        remote = item["filename"]
        file_type = item["file_type"]
        compress_and_check(base_url, remote, "Imagenes", file_type,
                           "lossless", "webp", args.timeout, results)
        lossy_algorithm = "jpeg" if name.lower().endswith((".jpg", ".bmp")) else "webp"
        compress_and_check(base_url, remote, "Imagenes", file_type,
                           "lossy", lossy_algorithm, args.timeout, results)

    # Audio: cubre FLAC, ALAC, MP3 y Opus y usa cada muestra al menos una vez.
    audio_cases = {
        "muestra.mp3": [("lossless", "flac"), ("lossy", "mp3")],
        "muestra.wav": [("lossless", "flac"), ("lossy", "mp3")],
        "muestra.ogg": [("lossy", "opus")],
        "muestra.flac": [("lossy", "mp3")],
        "muestra.aac": [("lossless", "alac")],
        "muestra.m4a": [("lossy", "opus")],
        "muestra.opus": [("lossless", "flac")],
        "muestra.wma": [("lossy", "mp3")],
    }
    for name, tests in audio_cases.items():
        item = uploaded.get(("Audio", name))
        if not item:
            continue
        for mode, algorithm in tests:
            compress_and_check(base_url, item["filename"], "Audio", item["file_type"],
                               mode, algorithm, args.timeout, results)

    # Vídeo: H.264 lossless/lossy y VP9. Se puede omitir con --skip-video.
    video_cases = {
        "muestra.mp4": ("lossy", "h264"),
        "muestra.webm": ("lossy", "vp9"),
        "muestra.mov": ("lossy", "vp9"),
        "muestra.mkv": ("lossless", "h264"),
        "muestra.avi": ("lossy", "h264"),
    }
    if not args.skip_video:
        for name, (mode, algorithm) in video_cases.items():
            item = uploaded.get(("Video", name))
            if not item:
                continue
            compress_and_check(base_url, item["filename"], "Video", item["file_type"],
                               mode, algorithm, args.timeout, results)

    # Texto: los cuatro compresores sin pérdida y la normalización con pérdida.
    text_item = uploaded.get(("Texto", "texto_prueba.txt"))
    if text_item:
        for algorithm in ("zlib", "gzip", "bz2", "lzma"):
            compress_and_check(base_url, text_item["filename"], "Texto", "text",
                               "lossless", algorithm, args.timeout, results)
        compress_and_check(base_url, text_item["filename"], "Texto", "text",
                           "lossy", "normalize", args.timeout, results)

    # Archivos .gz: se comprueba la subida y la descompresión directa.
    # TAR.GZ se descomprime a TAR; no se extraen sus archivos internos.
    for name in ("muestra.csv.gz", "muestra.tar.gz"):
        item = uploaded.get(("Comprimidos", name))
        if item:
            if item["file_type"] != "gzip":
                add_result(results, "Comprimidos", name, "detección GZIP", "ERROR",
                           f"Se esperaba tipo 'gzip', pero la API detectó '{item['file_type']}'.")
            else:
                add_result(results, "Comprimidos", name, "detección GZIP", "OK",
                           "archivo reconocido como GZIP")
            decompress_and_check(base_url, item["filename"], "Comprimidos",
                                 args.timeout, results)

    # TAR.BZ2 y TAR.XZ no tienen endpoint de descompresión en la versión actual.
    # Se suben como datos y se prueba Zlib sin pérdida sobre sus bytes.
    for name in ("muestra.tar.bz2", "muestra.tar.xz"):
        item = uploaded.get(("Comprimidos", name))
        if item:
            compress_and_check(base_url, item["filename"], "Comprimidos", "text",
                               "lossless", "zlib", args.timeout, results)

    # Salvar resultados en CSV y TXT junto al test.py.
    output_dir = Path(__file__).resolve().parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"test_results_{stamp}.csv"
    txt_path = output_dir / f"test_results_{stamp}.txt"

    fieldnames = ["categoria", "archivo", "prueba", "resultado", "duracion_segundos", "detalle"]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    total = len(results)
    ok_count = sum(row["resultado"] == "OK" for row in results)
    error_count = sum(row["resultado"] == "ERROR" for row in results)
    skipped_count = sum(row["resultado"] == "OMITIDA" for row in results)
    lines = [
        "INFORME DE PRUEBAS AUTOMÁTICAS - COMPRESOR MULTIMEDIA",
        "=" * 58,
        f"Fecha: {datetime.now().isoformat(timespec='seconds')}",
        f"Aplicación: {base_url}",
        f"Carpeta de muestras: {root}",
        f"Total: {total}",
        f"Correctas: {ok_count}",
        f"Errores: {error_count}",
        f"Omitidas: {skipped_count}",
        "",
        "DETALLE",
        "-" * 58,
    ]
    for row in results:
        lines.append(
            f"[{row['resultado']}] {row['categoria']}/{row['archivo']} | "
            f"{row['prueba']} | {row['duracion_segundos']} s | {row['detalle']}"
        )
    if missing_files:
        lines.extend(["", "ARCHIVOS LOCALES NO ENCONTRADOS:", *missing_files])
    lines.extend([
        "",
        "Notas:",
        "- Los archivos generados se guardan en la carpeta temp de la aplicación.",
        "- TAR.GZ se descomprime a un .tar; no se extrae el contenido interno.",
        "- TAR.BZ2 y TAR.XZ no tienen endpoint de descompresión en la versión actual.",
        "- El GIF puede perder la animación al convertirse mediante el código actual de Pillow.",
    ])
    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 65)
    print(f"Pruebas terminadas: {ok_count} OK, {error_count} ERROR, {skipped_count} OMITIDAS.")
    print(f"Informe TXT: {txt_path}")
    print(f"Resultados CSV: {csv_path}")
    if missing_files:
        print("Faltan algunos archivos de muestra; revisa las entradas OMITIDA en el informe.")
    if error_count:
        print("Hay pruebas fallidas. Abre el informe TXT o CSV para ver el endpoint y el error.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nPruebas canceladas por el usuario.")
        sys.exit(130)
