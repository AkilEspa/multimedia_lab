#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas automáticas de la aplicación FastAPI de compresión multimedia (Unittest).

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
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


# ============================================================================
# CONFIGURACIÓN Y CONSTANTES
# ============================================================================

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

# Diccionario global para compartir argumentos de CLI con la clase unittest
CONFIG = {
    "url": "http://127.0.0.1:8000",
    "folder": None,
    "timeout": 240,
    "skip_video": False
}


class ApiFailure(Exception):
    """Error HTTP/API con un mensaje que puede mostrarse en el informe."""


# ============================================================================
# FUNCIONES AUXILIARES (Peticiones HTTP y Sistema de Archivos)
# ============================================================================

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


# ============================================================================
# CLASE DE PRUEBAS UNITARIAS (unittest.TestCase)
# ============================================================================

class TestMultimediaCompression(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Se ejecuta una vez antes de todas las pruebas."""
        cls.base_url = CONFIG["url"].rstrip("/")
        cls.timeout = CONFIG["timeout"]
        cls.skip_video = CONFIG["skip_video"]
        
        cls.root = find_sample_folder(CONFIG["folder"])
        if cls.root is None:
            raise unittest.SkipTest("No se encuentra la carpeta multimedia_test_files. Abortando pruebas.")

        print(f"\nCarpeta de muestras: {cls.root}")
        print(f"Aplicación: {cls.base_url}")
        print("Comprobando conexión con FastAPI...")
        
        try:
            status, _, _ = get_response(cls.base_url + "/", timeout=min(cls.timeout, 15))
            if status != 200:
                raise unittest.SkipTest(f"La página principal respondió HTTP {status}.")
        except ApiFailure as exc:
            raise unittest.SkipTest(f"No se puede conectar con la aplicación: {exc}")

        cls.run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:5]
        cls.results: list[dict[str, str]] = []
        cls.uploaded: dict[tuple[str, str], dict[str, Any]] = {}
        cls.missing_files: list[str] = []

    @classmethod
    def tearDownClass(cls):
        """Se ejecuta al finalizar todas las pruebas para generar el informe CSV y TXT."""
        if not cls.results:
            return

        output_dir = Path(__file__).resolve().parent
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = output_dir / f"test_results_{stamp}.csv"
        txt_path = output_dir / f"test_results_{stamp}.txt"

        fieldnames = ["categoria", "archivo", "prueba", "resultado", "duracion_segundos", "detalle"]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(cls.results)

        total = len(cls.results)
        ok_count = sum(row["resultado"] == "OK" for row in cls.results)
        error_count = sum(row["resultado"] == "ERROR" for row in cls.results)
        skipped_count = sum(row["resultado"] == "OMITIDA" for row in cls.results)
        
        lines = [
            "INFORME DE PRUEBAS AUTOMÁTICAS - COMPRESOR MULTIMEDIA",
            "=" * 58,
            f"Fecha: {datetime.now().isoformat(timespec='seconds')}",
            f"Aplicación: {cls.base_url}",
            f"Carpeta de muestras: {cls.root}",
            f"Total: {total}",
            f"Correctas: {ok_count}",
            f"Errores: {error_count}",
            f"Omitidas: {skipped_count}",
            "",
            "DETALLE",
            "-" * 58,
        ]
        
        for row in cls.results:
            lines.append(
                f"[{row['resultado']}] {row['categoria']}/{row['archivo']} | "
                f"{row['prueba']} | {row['duracion_segundos']} s | {row['detalle']}"
            )
            
        if cls.missing_files:
            lines.extend(["", "ARCHIVOS LOCALES NO ENCONTRADOS:", *cls.missing_files])
            
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

    @classmethod
    def log_result(cls, category: str, filename: str, test_name: str, status: str, detail: str, duration: float = 0.0):
        """Registra el resultado de una prueba para los informes finales."""
        cls.results.append({
            "categoria": category,
            "archivo": filename,
            "prueba": test_name,
            "resultado": status,
            "duracion_segundos": f"{duration:.2f}",
            "detalle": detail.replace("\n", " ").strip(),
        })
        color = {"OK": "\033[92m", "ERROR": "\033[91m", "OMITIDA": "\033[93m"}.get(status, "")
        reset = "\033[0m" if color else ""
        # Imprime en consola para dar feedback en tiempo real
        print(f"[{color}{status}{reset}] {category}/{filename} — {test_name}: {detail} ({duration:.1f} s)")

    def helper_compress_check(self, original_filename: str, category: str, uploaded_type: str, mode: str, algorithm: str):
        """Función auxiliar que ejecuta la lógica de compresión y emite aserciones de unittest."""
        start = time.monotonic()
        test_name = f"compresión {mode}/{algorithm}"
        try:
            payload = post_form(self.base_url, "/compress", {
                "filename": original_filename,
                "file_type": uploaded_type,
                "mode": mode,
                "algorithm": algorithm,
            }, self.timeout)

            # Aserciones de las respuestas esperadas
            required = {"output_filename", "original_size", "compressed_size", "report_filename"}
            missing = sorted(required - payload.keys())
            self.assertEqual(len(missing), 0, f"Faltan campos en la respuesta: {', '.join(missing)}")

            output_name = str(payload["output_filename"])
            report_name = str(payload["report_filename"])
            
            download_ok, download_detail = verify_download(self.base_url, output_name, self.timeout)
            self.assertTrue(download_ok, f"No se pudo descargar el resultado: {download_detail}")

            report_ok, report_detail = verify_download(self.base_url, report_name, self.timeout)
            self.assertTrue(report_ok, f"No se pudo descargar el informe: {report_detail}")

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

            self.log_result(category, original_filename, test_name, "OK", summary, time.monotonic() - start)

        except Exception as exc:
            self.log_result(category, original_filename, test_name, "ERROR", str(exc), time.monotonic() - start)
            raise  # Vuelve a lanzar la excepción para que unittest la marque como fallo.

    def helper_decompress_check(self, original_filename: str, category: str):
        """Función auxiliar para la lógica de descompresión."""
        start = time.monotonic()
        try:
            payload = post_form(self.base_url, "/decompress-gzip", {
                "filename": original_filename,
            }, self.timeout)
            
            output_name = str(payload["output_filename"])
            size = int(payload.get("decompressed_size", 0))
            self.assertGreater(size, 0, "La API informó un resultado descomprimido vacío.")
            
            ok, detail = verify_download(self.base_url, output_name, self.timeout)
            self.assertTrue(ok, f"No se pudo descargar el archivo descomprimido: {detail}")
            
            self.log_result(category, original_filename, "descompresión GZIP", "OK",
                            f"generado {output_name} ({size} bytes); {detail}", time.monotonic() - start)
        except Exception as exc:
            self.log_result(category, original_filename, "descompresión GZIP", "ERROR", str(exc), time.monotonic() - start)
            raise


    # ========================================================================
    # PRUEBAS (El prefijo numérico garantiza el orden de ejecución en unittest)
    # ========================================================================

    def test_01_upload_files(self):
        """1. Carga de todos los archivos al servidor."""
        for category, names in EXPECTED_FILES.items():
            for name in names:
                if self.skip_video and category == "Video":
                    continue
                
                # Usamos subtests para que el fallo de un archivo no detenga los demás
                with self.subTest(file=f"{category}/{name}"):
                    local_path = self.root / category / name
                    if not local_path.is_file():
                        self.missing_files.append(f"{category}/{name}")
                        self.log_result(category, name, "archivo de muestra", "OMITIDA", "No se encontró el archivo local.")
                        self.skipTest(f"Archivo local no encontrado: {local_path}")
                        continue

                    remote_name = f"autotest_{self.run_id}_{category}_{name}"
                    try:
                        data = upload_file(self.base_url, local_path, category, remote_name, self.timeout)
                        self.uploaded[(category, name)] = {
                            "path": local_path,
                            "filename": str(data["filename"]),
                            "file_type": str(data.get("file_type", "")),
                        }
                        self.log_result(category, name, "subida", "OK", f"detectado como tipo '{data.get('file_type', 'desconocido')}'")
                    except Exception as exc:
                        self.log_result(category, name, "subida", "ERROR", str(exc))
                        raise

    def test_02_images(self):
        """2. Compresión de imágenes (Lossless y Lossy)."""
        for name in EXPECTED_FILES["Imagenes"]:
            item = self.uploaded.get(("Imagenes", name))
            if not item:
                continue
            
            remote = item["filename"]
            file_type = item["file_type"]
            lossy_algorithm = "jpeg" if name.lower().endswith((".jpg", ".bmp")) else "webp"

            with self.subTest(file=name, mode="lossless", alg="webp"):
                self.helper_compress_check(remote, "Imagenes", file_type, "lossless", "webp")
                
            with self.subTest(file=name, mode="lossy", alg=lossy_algorithm):
                self.helper_compress_check(remote, "Imagenes", file_type, "lossy", lossy_algorithm)

    def test_03_audio(self):
        """3. Compresión de audio (FLAC, ALAC, MP3, Opus)."""
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
            item = self.uploaded.get(("Audio", name))
            if not item:
                continue
                
            for mode, algorithm in tests:
                with self.subTest(file=name, mode=mode, alg=algorithm):
                    self.helper_compress_check(item["filename"], "Audio", item["file_type"], mode, algorithm)

    def test_04_video(self):
        """4. Compresión de vídeo (H.264, VP9)."""
        if self.skip_video:
            self.skipTest("Pruebas de vídeo omitidas por parámetro CLI.")
            
        video_cases = {
            "muestra.mp4": ("lossy", "h264"),
            "muestra.webm": ("lossy", "vp9"),
            "muestra.mov": ("lossy", "vp9"),
            "muestra.mkv": ("lossless", "h264"),
            "muestra.avi": ("lossy", "h264"),
        }
        for name, (mode, algorithm) in video_cases.items():
            item = self.uploaded.get(("Video", name))
            if not item:
                continue
                
            with self.subTest(file=name, mode=mode, alg=algorithm):
                self.helper_compress_check(item["filename"], "Video", item["file_type"], mode, algorithm)

    def test_05_text(self):
        """5. Compresión y normalización de texto."""
        text_item = self.uploaded.get(("Texto", "texto_prueba.txt"))
        if not text_item:
            self.skipTest("Archivo de texto no subido.")
            
        for algorithm in ("zlib", "gzip", "bz2", "lzma"):
            with self.subTest(alg=algorithm, mode="lossless"):
                self.helper_compress_check(text_item["filename"], "Texto", "text", "lossless", algorithm)
                
        with self.subTest(alg="normalize", mode="lossy"):
            self.helper_compress_check(text_item["filename"], "Texto", "text", "lossy", "normalize")

    def test_06_compressed_gzip(self):
        """6. Descompresión de archivos GZIP."""
        for name in ("muestra.csv.gz", "muestra.tar.gz"):
            item = self.uploaded.get(("Comprimidos", name))
            if not item:
                continue
                
            with self.subTest(file=name, test="detección_tipo"):
                if item["file_type"] != "gzip":
                    self.log_result("Comprimidos", name, "detección GZIP", "ERROR", f"Se esperaba 'gzip', detectado '{item['file_type']}'.")
                    self.assertEqual(item["file_type"], "gzip", f"Tipo incorrecto para {name}")
                else:
                    self.log_result("Comprimidos", name, "detección GZIP", "OK", "archivo reconocido como GZIP")
                    
            with self.subTest(file=name, test="descompresion"):
                self.helper_decompress_check(item["filename"], "Comprimidos")

    def test_07_compressed_tar(self):
        """7. Compresión Zlib sobre ficheros bz2 y xz (sin soporte de descompresión actual)."""
        for name in ("muestra.tar.bz2", "muestra.tar.xz"):
            item = self.uploaded.get(("Comprimidos", name))
            if not item:
                continue
            with self.subTest(file=name, alg="zlib"):
                self.helper_compress_check(item["filename"], "Comprimidos", "text", "lossless", "zlib")


# ============================================================================
# PUNTO DE ENTRADA (Manejo de argumentos de argparse vs unittest)
# ============================================================================

if __name__ == "__main__":
    # 1. Parseamos los argumentos personalizados primero sin interceptar "help"
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--folder", default=None)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--skip-video", action="store_true")

    args, remaining_argv = parser.parse_known_args()
    
    # Actualizamos la configuración global que usará la clase Test
    CONFIG.update(vars(args))
    
    # 2. Reconstruimos los argumentos para unittest
    # Añadimos sys.argv[0] (el nombre del script) y los argumentos restantes que pueden ser flags de unittest (ej. -v)
    unittest_argv = [sys.argv[0]] + remaining_argv
    
    print("Iniciando suite de pruebas Unittest...")
    
    try:
        # 3. Lanzamos unittest pasando explícitamente los argumentos procesados
        unittest.main(argv=unittest_argv)
    except KeyboardInterrupt:
        print("\nPruebas canceladas por el usuario.")
        sys.exit(130)