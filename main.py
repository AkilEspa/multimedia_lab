import os
import shutil
import zlib
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from PIL import Image
import imageio_ffmpeg
import ffmpeg

# Configurar automáticamente FFmpeg mediante el paquete de pip
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

app = FastAPI(title="App de Compresión Multimedia y Texto")

# Directorios temporales y de plantillas
UPLOAD_DIR = "temp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/temp", StaticFiles(directory=UPLOAD_DIR), name="temp")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Sube el archivo original y devuelve su ruta pública para previsualizarlo."""
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    return {"filename": file.filename, "url": f"/temp/{file.filename}"}

@app.post("/compress")
async def compress_file(
    filename: str = Form(...),
    file_type: str = Form(...),  # 'image', 'audio', 'video', 'text'
    mode: str = Form(...)        # 'lossless', 'lossy'
):
    input_path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    base_name, ext = os.path.splitext(filename)

    try:
        if file_type == "image":
            img = Image.open(input_path)
            if mode == "lossless":
                output_filename = f"{base_name}_lossless.webp"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                img.save(output_path, "WEBP", lossless=True)
            else:
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                output_filename = f"{base_name}_lossy.jpg"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                img.save(output_path, "JPEG", quality=50, optimize=True)

        elif file_type == "audio":
            if mode == "lossless":
                output_filename = f"{base_name}_lossless.flac"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                (
                    ffmpeg
                    .input(input_path)
                    .output(output_path, acodec='flac')
                    .global_args('-y')
                    .run(cmd=ffmpeg_path)
                )
            else:
                output_filename = f"{base_name}_lossy.mp3"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                (
                    ffmpeg
                    .input(input_path)
                    .output(output_path, acodec='libmp3lame', audio_bitrate='64k')
                    .global_args('-y')
                    .run(cmd=ffmpeg_path)
                )

        elif file_type == "video":
            if mode == "lossless":
                output_filename = f"{base_name}_lossless.mp4"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                (
                    ffmpeg
                    .input(input_path)
                    .output(output_path, vcodec='libx264', crf=0, acodec='copy')
                    .global_args('-y')
                    .run(cmd=ffmpeg_path)
                )
            else:
                output_filename = f"{base_name}_lossy.mp4"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                (
                    ffmpeg
                    .input(input_path)
                    .output(output_path, vcodec='libx264', crf=32, vf='scale=-2:480', acodec='aac', audio_bitrate='64k')
                    .global_args('-y')
                    .run(cmd=ffmpeg_path)
                )

        elif file_type == "text":
            with open(input_path, "rb") as f:
                content = f.read()
            if mode == "lossless":
                compressed_data = zlib.compress(content, level=9)
                output_filename = f"{base_name}_lossless.zlib"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with open(output_path, "wb") as f:
                    f.write(compressed_data)
            else:
                text_str = content.decode("utf-8", errors="ignore")
                lossy_text = " ".join(text_str.split())
                output_filename = f"{base_name}_lossy.txt"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(lossy_text)
        else:
            raise HTTPException(status_code=400, detail="Tipo de archivo no soportado")

        return {
            "output_filename": output_filename,
            "output_url": f"/temp/{output_filename}",
            "original_size": os.path.getsize(input_path),
            "compressed_size": os.path.getsize(output_path)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    raise HTTPException(status_code=404, detail="Archivo no encontrado")