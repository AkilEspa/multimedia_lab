import bz2
import gzip
import lzma
import math
import os
import re
import shutil
import subprocess
import zlib

import ffmpeg
import imageio_ffmpeg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageChops, ImageStat
from starlette.requests import Request


ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

app = FastAPI(title="App de Compresión Multimedia y Texto")


UPLOAD_DIR = "temp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/temp", StaticFiles(directory=UPLOAD_DIR), name="temp")
templates = Jinja2Templates(directory="templates")


SUPPORTED_ALGORITHMS = {
    "image": {
        "lossless": {"webp", "png"},
        "lossy": {"webp", "jpeg"},
    },
    "audio": {
        "lossless": {"flac", "alac"},
        "lossy": {"mp3", "opus"},
    },
    "video": {
        "lossless": {"h264"},
        "lossy": {"h264", "vp9"},
    },
    "text": {
        "lossless": {"zlib", "gzip", "bz2", "lzma"},
        "lossy": {"normalize"},
    },
}


def safe_filename(filename: str) -> str:

    return os.path.basename(filename or "archivo")


def calculate_image_metrics(original_path: str, output_path: str) -> dict:

    original = Image.open(original_path).convert("RGB")
    compressed = Image.open(output_path).convert("RGB")

    if original.size != compressed.size:
        return {
            "mse": None,
            "psnr_db": None,
            "note": "No se pudo calcular MSE/PSNR porque las dimensiones difieren.",
        }

    diff = ImageChops.difference(original, compressed)

    rms = ImageStat.Stat(diff).rms

    mse = sum(value * value for value in rms) / len(rms)

    if mse == 0:
        psnr = None
        psnr_infinite = True
    else:
        psnr = 10 * math.log10((255 ** 2) / mse)
        psnr_infinite = False

    return {
        "mse": mse,
        "psnr_db": psnr,
        "psnr_infinite": psnr_infinite,
        "note": None,
    }


def calculate_video_psnr(original_path: str, output_path: str):
    
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "info",
        "-i",
        original_path,
        "-i",
        output_path,
        "-lavfi",
        "[0:v][1:v]psnr",
        "-f",
        "null",
        "-",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        output = result.stdout + "\n" + result.stderr

        matches = re.findall(
            r"average:([0-9]+(?:\.[0-9]+)?)",
            output
        )

        if matches:
            return float(matches[-1])

    except Exception:
        pass

    return None


def get_media_info(path: str) -> dict:

    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", path],
            capture_output=True,
            text=True,
            check=False,
        )

        stderr = result.stderr

        duration_match = re.search(
            r"Duration: (\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
            stderr
        )

        bitrate_match = re.search(
            r"bitrate: (\d+) kb/s",
            stderr
        )

        return {
            "duration": duration_match.group(1)
            if duration_match else None,

            "bitrate_kbps": int(bitrate_match.group(1))
            if bitrate_match else None,
        }

    except Exception:
        return {
            "duration": None,
            "bitrate_kbps": None,
        }


def build_metrics(
    original_path: str,
    output_path: str,
    file_type: str
) -> dict:

    original_size = os.path.getsize(original_path)
    output_size = os.path.getsize(output_path)

    if original_size > 0:
        reduction = (
            1 - output_size / original_size
        ) * 100
    else:
        reduction = 0

    if output_size > 0:
        compression_ratio = original_size / output_size
    else:
        compression_ratio = None

    metrics = {
        "original_size": original_size,
        "compressed_size": output_size,
        "reduction_percent": reduction,
        "compression_ratio": compression_ratio,
    }

    if file_type == "image":

        metrics.update(
            calculate_image_metrics(
                original_path,
                output_path
            )
        )

    elif file_type == "video":

        metrics["psnr_db"] = calculate_video_psnr(
            original_path,
            output_path
        )

    elif file_type == "audio":

        metrics["original_media_info"] = get_media_info(
            original_path
        )

        metrics["compressed_media_info"] = get_media_info(
            output_path
        )

    return metrics


def create_report(
    report_filename: str,
    original_filename: str,
    output_filename: str,
    file_type: str,
    mode: str,
    requested_algorithm: str,
    effective_algorithm: str,
    metrics: dict,
    skipped: bool
):

    lines = [

        "INFORME DE COMPRESIÓN MULTIMEDIA",
        "=" * 40,

        f"Archivo original: {original_filename}",
        f"Tipo: {file_type}",
        f"Modo: {mode}",
        f"Algoritmo solicitado: {requested_algorithm}",
        f"Algoritmo aplicado: {effective_algorithm}",
        f"Archivo de salida: {output_filename}",

        "",

        "MÉTRICAS DE COMPRESIÓN",

        f"Tamaño original: "
        f"{metrics['original_size']} bytes",

        f"Tamaño resultado: "
        f"{metrics['compressed_size']} bytes",

        f"Reducción: "
        f"{metrics['reduction_percent']:.2f}%"
    ]

    if metrics.get("compression_ratio") is not None:

        lines.append(
            f"Ratio de compresión: "
            f"{metrics['compression_ratio']:.4f}"
        )

    # Métricas de imágenes
    if file_type == "image":

        mse = metrics.get("mse")
        psnr = metrics.get("psnr_db")

        lines.append("")
        lines.append("MÉTRICAS DE CALIDAD DE IMAGEN")

        if mse is not None:
            lines.append(
                f"MSE: {mse:.6f}"
            )
        else:
            lines.append(
                "MSE: No disponible"
            )

        if metrics.get("psnr_infinite"):

            lines.append(
                "PSNR: infinito "
                "(imagen idéntica a la original)"
            )

        elif psnr is None:

            lines.append(
                "PSNR: No disponible"
            )

        else:

            lines.append(
                f"PSNR: {psnr:.4f} dB"
            )

    # Métricas de vídeo
    elif file_type == "video":

        psnr = metrics.get("psnr_db")

        lines.append("")
        lines.append("MÉTRICAS DE CALIDAD DE VÍDEO")

        if psnr is None:

            lines.append(
                "PSNR: No disponible "
                "(las secuencias no pudieron compararse automáticamente)"
            )

        else:

            lines.append(
                f"PSNR: {psnr:.4f} dB"
            )

    # Métricas de audio
    elif file_type == "audio":

        original_info = metrics.get(
            "original_media_info",
            {}
        )

        compressed_info = metrics.get(
            "compressed_media_info",
            {}
        )

        lines.append("")
        lines.append("MÉTRICAS DE AUDIO")

        if original_info.get("duration"):

            lines.append(
                f"Duración original: "
                f"{original_info['duration']}"
            )

        if compressed_info.get("duration"):

            lines.append(
                f"Duración resultado: "
                f"{compressed_info['duration']}"
            )

        if original_info.get("bitrate_kbps") is not None:

            lines.append(
                f"Bitrate original: "
                f"{original_info['bitrate_kbps']} kb/s"
            )

        if compressed_info.get("bitrate_kbps") is not None:

            lines.append(
                f"Bitrate resultado: "
                f"{compressed_info['bitrate_kbps']} kb/s"
            )

        lines.append(
            "Nota: el bitrate se muestra como "
            "métrica objetiva de audio."
        )

    lines.append("")
    lines.append("OBSERVACIÓN")

    if skipped:

        lines.append(
            "No se aplicó la compresión porque "
            "el resultado sin pérdida ocupaba más "
            "o lo mismo que el original. "
            "Se conservó el archivo original."
        )

    else:

        lines.append(
            "La compresión se aplicó normalmente."
        )

    report_path = os.path.join(
        UPLOAD_DIR,
        report_filename
    )

    with open(
        report_path,
        "w",
        encoding="utf-8"
    ) as report_file:

        report_file.write(
            "\n".join(lines)
        )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):

    return templates.TemplateResponse(
        request,
        "index.html"
    )


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...)
):

    filename = safe_filename(
        file.filename
    )

    file_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    with open(file_path, "wb") as buffer:

        shutil.copyfileobj(
            file.file,
            buffer
        )

    lower_name = filename.lower()

    # Detectar GZIP
    if (
        lower_name.endswith(".gz")
        or file.content_type == "application/gzip"
    ):

        detected_type = "gzip"

    elif (file.content_type or "").startswith("image/"):

        detected_type = "image"

    elif (file.content_type or "").startswith("audio/"):

        detected_type = "audio"

    elif (file.content_type or "").startswith("video/"):

        detected_type = "video"

    elif lower_name.endswith(
        (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")
    ):

        detected_type = "image"

    elif lower_name.endswith(
        (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus")
    ):

        detected_type = "audio"

    elif lower_name.endswith(
        (".mp4", ".mkv", ".avi", ".mov", ".webm")
    ):

        detected_type = "video"

    else:

        detected_type = "text"

    return {
        "filename": filename,
        "url": f"/temp/{filename}",
        "file_type": detected_type,
    }


@app.post("/compress")
async def compress_file(

    filename: str = Form(...),

    file_type: str = Form(...),

    mode: str = Form(...),

    algorithm: str = Form(...)
):

    filename = safe_filename(filename)

    input_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    if not os.path.exists(input_path):

        raise HTTPException(
            status_code=404,
            detail="Archivo no encontrado"
        )

    if (
        file_type not in SUPPORTED_ALGORITHMS
        or mode not in SUPPORTED_ALGORITHMS[file_type]
    ):

        raise HTTPException(
            status_code=400,
            detail="Tipo o modo de compresión no soportado"
        )

    if (
        algorithm
        not in SUPPORTED_ALGORITHMS[file_type][mode]
    ):

        raise HTTPException(
            status_code=400,
            detail="Algoritmo no compatible con el tipo y modo seleccionados"
        )

    base_name, ext = os.path.splitext(
        filename
    )

    output_filename = None
    output_path = None

    try:


        if file_type == "image":

            img = Image.open(input_path)

            if (
                mode == "lossless"
                and algorithm == "webp"
            ):

                output_filename = (
                    f"{base_name}_lossless.webp"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                img.save(
                    output_path,
                    "WEBP",
                    lossless=True,
                    method=6
                )

            elif (
                mode == "lossless"
                and algorithm == "png"
            ):

                output_filename = (
                    f"{base_name}_lossless.png"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                img.save(
                    output_path,
                    "PNG",
                    optimize=True
                )

            elif (
                mode == "lossy"
                and algorithm == "jpeg"
            ):

                output_filename = (
                    f"{base_name}_lossy.jpg"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")

                img.save(
                    output_path,
                    "JPEG",
                    quality=50,
                    optimize=True,
                    progressive=True
                )

            elif (
                mode == "lossy"
                and algorithm == "webp"
            ):

                output_filename = (
                    f"{base_name}_lossy.webp"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                img.save(
                    output_path,
                    "WEBP",
                    quality=50,
                    method=6
                )


        elif file_type == "audio":

            if (
                mode == "lossless"
                and algorithm == "flac"
            ):

                output_filename = (
                    f"{base_name}_lossless.flac"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        acodec="flac",
                        compression_level=8
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )

            elif (
                mode == "lossless"
                and algorithm == "alac"
            ):

                output_filename = (
                    f"{base_name}_lossless_alac.m4a"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        acodec="alac"
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )

            elif (
                mode == "lossy"
                and algorithm == "mp3"
            ):

                output_filename = (
                    f"{base_name}_lossy.mp3"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        acodec="libmp3lame",
                        audio_bitrate="64k"
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )

            elif (
                mode == "lossy"
                and algorithm == "opus"
            ):

                output_filename = (
                    f"{base_name}_lossy.opus"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        acodec="libopus",
                        audio_bitrate="64k"
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )


        elif file_type == "video":

            if (
                mode == "lossless"
                and algorithm == "h264"
            ):

                output_filename = (
                    f"{base_name}_lossless.mkv"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        vcodec="libx264",
                        crf=0,
                        acodec="copy"
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )

            elif (
                mode == "lossy"
                and algorithm == "h264"
            ):

                output_filename = (
                    f"{base_name}_lossy_h264.mp4"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        vcodec="libx264",
                        crf=28,
                        acodec="aac",
                        audio_bitrate="96k"
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )

            elif (
                mode == "lossy"
                and algorithm == "vp9"
            ):

                output_filename = (
                    f"{base_name}_lossy_vp9.webm"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                (
                    ffmpeg
                    .input(input_path)
                    .output(
                        output_path,
                        vcodec="libvpx-vp9",
                        crf=32,
                        **{
                            "b:v": "0",
                            "b:a": "96k"
                        },
                        acodec="libopus"
                    )
                    .global_args("-y")
                    .run(cmd=ffmpeg_path)
                )


        elif file_type == "text":

            with open(
                input_path,
                "rb"
            ) as input_file:

                content = input_file.read()

            if (
                mode == "lossless"
                and algorithm == "zlib"
            ):

                compressed_data = zlib.compress(
                    content,
                    level=9
                )

                output_filename = (
                    f"{base_name}_lossless.zlib"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        compressed_data
                    )

            elif (
                mode == "lossless"
                and algorithm == "gzip"
            ):

                output_filename = (
                    f"{base_name}_lossless.gz"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                with gzip.open(
                    output_path,
                    "wb",
                    compresslevel=9
                ) as output_file:

                    output_file.write(
                        content
                    )

            elif (
                mode == "lossless"
                and algorithm == "bz2"
            ):

                compressed_data = bz2.compress(
                    content,
                    compresslevel=9
                )

                output_filename = (
                    f"{base_name}_lossless.bz2"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        compressed_data
                    )

            elif (
                mode == "lossless"
                and algorithm == "lzma"
            ):

                compressed_data = lzma.compress(
                    content,
                    preset=9
                )

                output_filename = (
                    f"{base_name}_lossless.xz"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        compressed_data
                    )

            elif (
                mode == "lossy"
                and algorithm == "normalize"
            ):

                text_str = content.decode(
                    "utf-8",
                    errors="ignore"
                )

                lossy_text = " ".join(
                    text_str.split()
                )

                output_filename = (
                    f"{base_name}_lossy.txt"
                )

                output_path = os.path.join(
                    UPLOAD_DIR,
                    output_filename
                )

                with open(
                    output_path,
                    "w",
                    encoding="utf-8"
                ) as output_file:

                    output_file.write(
                        lossy_text
                    )


        if (
            output_path is None
            or not os.path.exists(output_path)
        ):

            raise HTTPException(
                status_code=500,
                detail="No se pudo generar el archivo comprimido"
            )


        original_size = os.path.getsize(input_path)
        generated_size = os.path.getsize(output_path)

        skipped = False
        effective_algorithm = algorithm

        # Si el resultado no reduce el tamaño, se descarta
        # independientemente de si el modo es lossless o lossy.
        if generated_size >= original_size:

            # Eliminar el resultado que ocupa más o lo mismo
            os.remove(output_path)

            # Conservar el archivo original
            output_filename = filename
            output_path = input_path

            skipped = True

            effective_algorithm = "original_conservado"


        metrics = build_metrics(
            input_path,
            output_path,
            file_type
        )


        report_filename = (
            f"{base_name}_informe.txt"
        )

        create_report(
            report_filename,
            filename,
            output_filename,
            file_type,
            mode,
            algorithm,
            effective_algorithm,
            metrics,
            skipped
        )

        preview_supported = not (
            file_type == "text"
            and mode == "lossless"
            and not skipped
        )


        return {

            "output_filename":
                output_filename,

            "output_url":
                f"/temp/{output_filename}",

            "original_size":
                metrics["original_size"],

            "compressed_size":
                metrics["compressed_size"],

            "attempted_size": generated_size,

            "reduction_percent":
                metrics["reduction_percent"],

            "compression_ratio":
                metrics["compression_ratio"],

            "metrics":
                metrics,

            "algorithm":
                effective_algorithm,

            "skipped":
                skipped,

            "preview_supported":
                preview_supported,

            "report_filename":
                report_filename,

            "report_url":
                f"/download/{report_filename}"
        }


    except HTTPException:
        raise

    except ffmpeg.Error as error:

        details = (
            error.stderr.decode(
                "utf-8",
                errors="ignore"
            )
            if error.stderr
            else str(error)
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "FFmpeg no pudo procesar el archivo: "
                + details[-1500:]
            )
        )

    except Exception as error:

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.post("/decompress-gzip")
async def decompress_gzip(
    filename: str = Form(...)
):

    filename = safe_filename(filename)

    input_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    if not os.path.exists(input_path):

        raise HTTPException(
            status_code=404,
            detail="Archivo GZIP no encontrado"
        )

    if not filename.lower().endswith(".gz"):

        raise HTTPException(
            status_code=400,
            detail="El archivo no tiene extensión .gz"
        )

    # Quitar .gz
    base_name = filename[:-3]

    root, original_ext = os.path.splitext(
        base_name
    )

    if original_ext:

        output_filename = (
            f"{root}_decompressed{original_ext}"
        )

    else:

        output_filename = (
            f"{base_name}_decompressed.txt"
        )

    output_path = os.path.join(
        UPLOAD_DIR,
        output_filename
    )

    try:

        with gzip.open(
            input_path,
            "rb"
        ) as compressed_file:

            data = compressed_file.read()

        with open(
            output_path,
            "wb"
        ) as output_file:

            output_file.write(data)


        return {

            "output_filename":
                output_filename,

            "output_url":
                f"/temp/{output_filename}",

            "original_size":
                os.path.getsize(input_path),

            "decompressed_size":
                len(data),

            "preview_type":
                "text"
        }


    except (
        gzip.BadGzipFile,
        OSError,
        EOFError
    ) as error:

        raise HTTPException(
            status_code=400,
            detail=(
                "El archivo GZIP no es válido "
                f"o está dañado: {error}"
            )
        )


@app.get("/download/{filename}")
async def download_file(
    filename: str
):

    filename = safe_filename(filename)

    file_path = os.path.join(
        UPLOAD_DIR,
        filename
    )

    if os.path.exists(file_path):

        return FileResponse(
            file_path,
            filename=filename
        )

    raise HTTPException(
        status_code=404,
        detail="Archivo no encontrado"
    )