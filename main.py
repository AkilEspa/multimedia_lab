import bz2
import gzip
import lzma
import math
import os
import re
import shutil
import subprocess
import zlib
import io
from datetime import datetime

# Configurar Matplotlib en modo 'Agg' ANTES de importar pyplot (imprescindible para Docker/servidores sin pantalla)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Importaciones de ReportLab para maquetación avanzada estilo LaTeX
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

import ffmpeg
import imageio_ffmpeg
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image as PILImage, ImageChops, ImageStat
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
    original = PILImage.open(original_path).convert("RGB")
    compressed = PILImage.open(output_path).convert("RGB")

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
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        output = result.stdout + "\n" + result.stderr
        matches = re.findall(r"average:([0-9]+(?:\.[0-9]+)?)", output)
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
        duration_match = re.search(r"Duration: (\d{2}:\d{2}:\d{2}(?:\.\d+)?)", stderr)
        bitrate_match = re.search(r"bitrate: (\d+) kb/s", stderr)
        return {
            "duration": duration_match.group(1) if duration_match else None,
            "bitrate_kbps": int(bitrate_match.group(1)) if bitrate_match else None,
        }
    except Exception:
        return {"duration": None, "bitrate_kbps": None}


def build_metrics(original_path: str, output_path: str, file_type: str) -> dict:
    original_size = os.path.getsize(original_path)
    output_size = os.path.getsize(output_path)

    reduction = (1 - output_size / original_size) * 100 if original_size > 0 else 0
    compression_ratio = original_size / output_size if output_size > 0 else None

    metrics = {
        "original_size": original_size,
        "compressed_size": output_size,
        "reduction_percent": reduction,
        "compression_ratio": compression_ratio,
    }

    if file_type == "image":
        metrics.update(calculate_image_metrics(original_path, output_path))
    elif file_type == "video":
        metrics["psnr_db"] = calculate_video_psnr(original_path, output_path)
    elif file_type == "audio":
        metrics["original_media_info"] = get_media_info(original_path)
        metrics["compressed_media_info"] = get_media_info(output_path)

    return metrics


# ==============================================================================
# CLASE CANVAS PARA CABECERAS Y PIES DE PÁGINA ESTILO LATEX (Página X de Y)
# ==============================================================================
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Times-Roman", 9)
        self.setFillColor(HexColor("#4A5568"))
        page_w, page_h = self._pagesize
        margin = 45

        # Línea de cabecera superior
        self.setStrokeColor(HexColor("#CBD5E0"))
        self.setLineWidth(0.6)
        self.line(margin, page_h - 40, page_w - margin, page_h - 40)
        self.drawString(margin, page_h - 35, "INFORME TÉCNICO DE COMPRESIÓN MULTIMEDIA")
        self.drawRightString(page_w - margin, page_h - 35, "PROYECTO DRAG & DROP")

        # Línea de pie de página
        self.line(margin, 45, page_w - margin, 45)
        self.drawString(margin, 30, "Documento generado automáticamente con ReportLab Engine")
        self.drawRightString(page_w - margin, 30, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


# ==============================================================================
# GENERACIÓN DEL GRÁFICO EN ALTA RESOLUCIÓN CON MATPLOTLIB
# ==============================================================================
def generate_matplotlib_chart(metrics: dict, skipped: bool) -> io.BytesIO:
    # Ajustes estéticos tipo publicación LaTeX
    plt.rcParams['font.sans-serif'] = 'DejaVu Sans'
    plt.rcParams['font.size'] = 9.5
    
    orig_kb = metrics.get('original_size', 0) / 1024.0
    comp_kb = metrics.get('compressed_size', 0) / 1024.0
    reduction = metrics.get('reduction_percent', 0.0)

    fig, ax = plt.subplots(figsize=(6.2, 2.8), dpi=300)
    
    categorias = ['Original', 'Procesado']
    valores = [orig_kb, comp_kb]
    colores = ['#1A365D', '#2B6CB0' if not skipped else '#C53030']

    bars = ax.bar(categorias, valores, color=colores, width=0.4, edgecolor='#0D1B2A', linewidth=0.8)

    # Anotar valores sobre cada barra sin cortes
    for bar in bars:
        h = bar.get_height()
        ax.annotate(
            f"{h:.1f} KB",
            xy=(bar.get_x() + bar.get_width() / 2, h),
            xytext=(0, 4),
            textcoords="offset points",
            ha='center', va='bottom',
            fontsize=9, fontweight='bold', color='#1A365D'
        )

    ax.set_ylabel('Tamaño (KB)', fontsize=10, fontweight='bold', color='#1A365D')
    ax.set_title('Comparativa de Tamaño de Archivo', fontsize=11, fontweight='bold', pad=12, color='#1A365D')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#CBD5E0')
    ax.spines['bottom'].set_color('#CBD5E0')
    ax.yaxis.grid(True, linestyle='--', alpha=0.5, color='#CBD5E0')
    ax.set_axisbelow(True)

    # Incrementar el límite Y para dejar espacio a los textos superiores
    max_h = max(valores) if valores else 1
    ax.set_ylim(0, max_h * 1.25)

    fig.tight_layout()
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', dpi=300, bbox_inches='tight')
    buffer.seek(0)
    plt.close(fig)
    return buffer


# ==============================================================================
# GENERACIÓN DEL INFORME EN PDF ESTILO LATEX CON REPORTLAB
# ==============================================================================
def create_report(
    report_filename: str,
    original_filename: str,
    output_filename: str,
    file_type: str,
    mode: str,
    requested_algorithm: str,
    effective_algorithm: str,
    metrics: dict,
    skipped: bool,
    autor: str = "José Felix Barba Rojas y Akil Espadas Jiménez"
):
    report_path = os.path.join(UPLOAD_DIR, report_filename)

    # Documento con márgenes ajustados (45pt ~ 1.6cm)
    doc = SimpleDocTemplate(
        report_path,
        pagesize=letter,
        leftMargin=45,
        rightMargin=45,
        topMargin=55,
        bottomMargin=55
    )

    # Estilos tipográficos en Times New Roman
    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        'LatexTitle',
        fontName='Times-Bold',
        fontSize=20,
        leading=24,
        textColor=HexColor('#1A365D'),
        alignment=0,
        spaceAfter=6
    )

    style_subtitle = ParagraphStyle(
        'LatexSubtitle',
        fontName='Times-Italic',
        fontSize=12,
        leading=15,
        textColor=HexColor('#4A5568'),
        spaceAfter=12
    )

    style_author = ParagraphStyle(
        'LatexAuthor',
        fontName='Times-Roman',
        fontSize=10,
        leading=14,
        textColor=HexColor('#2D3748'),
        spaceAfter=15
    )

    style_heading = ParagraphStyle(
        'LatexHeading',
        fontName='Times-Bold',
        fontSize=13,
        leading=16,
        textColor=HexColor('#1A365D'),
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True
    )

    style_body = ParagraphStyle(
        'LatexBody',
        fontName='Times-Roman',
        fontSize=10,
        leading=14,
        textColor=HexColor('#2D3748'),
        spaceAfter=8
    )

    style_caption = ParagraphStyle(
        'LatexCaption',
        fontName='Times-Italic',
        fontSize=9,
        leading=12,
        textColor=HexColor('#718096'),
        alignment=1,
        spaceBefore=6,
        spaceAfter=12
    )

    style_cell_header = ParagraphStyle(
        'CellHeader',
        fontName='Times-Bold',
        fontSize=9.5,
        leading=12,
        textColor=colors.white
    )

    style_cell_body = ParagraphStyle(
        'CellBody',
        fontName='Times-Roman',
        fontSize=9,
        leading=12,
        textColor=HexColor('#2D3748')
    )

    story = []

    # 1. CABECERA Y PORTADA ESTILO ARTICLE DE LATEX
    story.append(HRFlowable(width="100%", thickness=2, color=HexColor('#1A365D'), spaceBefore=0, spaceAfter=10))
    story.append(Paragraph("INFORME TÉCNICO DE COMPRESIÓN MULTIMEDIA", style_title))
    story.append(Paragraph("Evaluación Cualitativa y Cuantitativa de Procesamiento de Archivos", style_subtitle))
    
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    info_autores = f"<b>Autores:</b> {autor}<br/><b>Fecha de Ejecución:</b> {fecha_actual}<br/><b>Motor de Procesamiento:</b> FastAPI Multimedia Pipeline"
    story.append(Paragraph(info_autores, style_author))
    story.append(HRFlowable(width="100%", thickness=0.8, color=HexColor('#CBD5E0'), spaceBefore=0, spaceAfter=12))

    # 2. RESUMEN / ABSTRACT EN CAJA DESTACADA
    abstract_text = (
        f"<b>Resumen:</b> Se ha procesado el archivo original <i>{original_filename}</i> "
        f"mediante el algoritmo <b>{effective_algorithm.upper()}</b> en modo <b>{mode.upper()}</b>. "
        f"Se registró un tamaño inicial de {(metrics['original_size']/1024):.2f} KB "
        f"y un tamaño final de {(metrics['compressed_size']/1024):.2f} KB, "
        f"representando una variación de <b>{metrics.get('reduction_percent', 0):.2f}%</b>."
    )
    if skipped:
        abstract_text += " <font color='#C53030'><b>[Nota: Se conservó el archivo original al no obtener una reducción de tamaño efectiva]</b></font>."

    abstract_table = Table(
        [[Paragraph(abstract_text, style_body)]],
        colWidths=[520]
    )
    abstract_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#F7FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.8, HexColor('#CBD5E0')),
        ('LINELEFT', (0, 0), (0, -1), 3.5, HexColor('#1A365D')),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(abstract_table)
    story.append(Spacer(1, 10))

    # 3. SECCIÓN 1: DATOS DEL PROCESAMIENTO (TABLA BOOKTABS)
    story.append(Paragraph("1. Parámetros de la Operación", style_heading))
    
    datos_tabla = [
        [Paragraph("Parámetro", style_cell_header), Paragraph("Valor Registrado", style_cell_header)],
        [Paragraph("Archivo Entrada", style_cell_body), Paragraph(original_filename, style_cell_body)],
        [Paragraph("Archivo Salida", style_cell_body), Paragraph(output_filename, style_cell_body)],
        [Paragraph("Tipo de Medio", style_cell_body), Paragraph(file_type.capitalize(), style_cell_body)],
        [Paragraph("Modo de Compresión", style_cell_body), Paragraph(mode.capitalize(), style_cell_body)],
        [Paragraph("Algoritmo Solicitado", style_cell_body), Paragraph(requested_algorithm, style_cell_body)],
        [Paragraph("Algoritmo Efectivo", style_cell_body), Paragraph(effective_algorithm, style_cell_body)],
        [Paragraph("Estado de Optimización", style_cell_body), Paragraph("Conservado Original" if skipped else "Comprimido con Éxito", style_cell_body)]
    ]

    t_params = Table(datos_tabla, colWidths=[200, 320])
    t_params.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1A365D')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#FFFFFF'), HexColor('#F7FAFC')]),
        ('LINEABOVE', (0, 0), (-1, 0), 1.2, HexColor('#1A365D')),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, HexColor('#1A365D')),
        ('LINEBELOW', (0, -1), (-1, -1), 1.2, HexColor('#1A365D')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_params)
    story.append(Spacer(1, 10))

    # 4. SECCIÓN 2: MÉTRICAS TÉCNICAS
    story.append(Paragraph("2. Métricas Técnicas y Calidad", style_heading))
    
    metricas_tabla = [
        [Paragraph("Métrica", style_cell_header), Paragraph("Valor", style_cell_header), Paragraph("Unidad / Detalle", style_cell_header)],
        [Paragraph("Tamaño Original", style_cell_body), Paragraph(f"{metrics['original_size']:,}", style_cell_body), Paragraph("Bytes", style_cell_body)],
        [Paragraph("Tamaño Procesado", style_cell_body), Paragraph(f"{metrics['compressed_size']:,}", style_cell_body), Paragraph("Bytes", style_cell_body)],
        [Paragraph("Porcentaje de Reducción", style_cell_body), Paragraph(f"{metrics.get('reduction_percent', 0):.2f}%", style_cell_body), Paragraph("Eficiencia de espacio", style_cell_body)],
        [Paragraph("Ratio de Compresión", style_cell_body), Paragraph(f"{metrics.get('compression_ratio', 0):.2f}:1" if metrics.get('compression_ratio') else "N/D", style_cell_body), Paragraph("Factor de reducción", style_cell_body)],
    ]

    # Agregar métricas específicas según el tipo de archivo
    if file_type == "image":
        mse_val = f"{metrics.get('mse'):.4f}" if metrics.get('mse') is not None else "N/A"
        psnr_val = "Infinito" if metrics.get("psnr_infinite") else (f"{metrics.get('psnr_db'):.2f} dB" if metrics.get('psnr_db') else "N/A")
        metricas_tabla.append([Paragraph("Error Cuadrático Medio (MSE)", style_cell_body), Paragraph(mse_val, style_cell_body), Paragraph("Diferencia entre píxeles", style_cell_body)])
        metricas_tabla.append([Paragraph("PSNR", style_cell_body), Paragraph(psnr_val, style_cell_body), Paragraph("Relación señal/ruido", style_cell_body)])
    elif file_type == "video":
        psnr_val = f"{metrics.get('psnr_db'):.2f} dB" if metrics.get('psnr_db') else "N/A"
        metricas_tabla.append([Paragraph("PSNR Vídeo Promedio", style_cell_body), Paragraph(psnr_val, style_cell_body), Paragraph("Evaluado con FFmpeg", style_cell_body)])
    elif file_type == "audio":
        orig_info = metrics.get("original_media_info", {})
        comp_info = metrics.get("compressed_media_info", {})
        metricas_tabla.append([Paragraph("Bitrate Original", style_cell_body), Paragraph(f"{orig_info.get('bitrate_kbps', 'N/D')} kb/s", style_cell_body), Paragraph("Flujo de datos original", style_cell_body)])
        metricas_tabla.append([Paragraph("Bitrate Resultado", style_cell_body), Paragraph(f"{comp_info.get('bitrate_kbps', 'N/D')} kb/s", style_cell_body), Paragraph("Flujo de datos procesado", style_cell_body)])

    t_metrics = Table(metricas_tabla, colWidths=[200, 150, 170])
    t_metrics.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1A365D')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#FFFFFF'), HexColor('#F7FAFC')]),
        ('LINEABOVE', (0, 0), (-1, 0), 1.2, HexColor('#1A365D')),
        ('LINEBELOW', (0, 0), (-1, 0), 1.2, HexColor('#1A365D')),
        ('LINEBELOW', (0, -1), (-1, -1), 1.2, HexColor('#1A365D')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(t_metrics)
    story.append(Spacer(1, 10))

    # 5. SECCIÓN 3: GRÁFICO CENTRADO Y SIN CORTES
    story.append(Paragraph("3. Representación Gráfica", style_heading))
    chart_buffer = generate_matplotlib_chart(metrics, skipped)
    
    # Imagen centrada horizontalmente
    img_chart = Image(chart_buffer, width=440, height=200)
    img_chart.hAlign = 'CENTER'
    
    # KeepTogether asegura que la gráfica y su pie de figura no se separen entre páginas
    story.append(KeepTogether([
        img_chart,
        Paragraph("Figura 1: Comparativa cuantitativa de tamaño en Kilobytes (KB) entre el archivo de origen y el resultado.", style_caption)
    ]))

    # 6. SECCIÓN 4: CONCLUSIONES TÉCNICAS
    story.append(Paragraph("4. Conclusiones y Observaciones", style_heading))
    if skipped:
        concl_text = (
            "• El algoritmo aplicado no produjo un archivo de menor peso que el original. <br/>"
            "• En cumplimiento con la directiva de eficiencia, el sistema descartó el resultado inflado y conservó el archivo de origen sin pérdidas de calidad adicional."
        )
    else:
        concl_text = (
            f"• La compresión mediante el algoritmo <b>{effective_algorithm}</b> concluyó exitosamente.<br/>"
            f"• Se logró una optimización del espacio de almacenamiento del <b>{metrics.get('reduction_percent', 0):.2f}%</b>.<br/>"
            "• El archivo resultante se encuentra disponible para su descarga directa en la plataforma."
        )
    story.append(Paragraph(concl_text, style_body))

    # Construir el documento PDF con nuestro NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)


# ==============================================================================
# ENDPOINTS Y LÓGICA EXISTENTE DE FASTAPI
# ==============================================================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    filename = safe_filename(file.filename)
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    lower_name = filename.lower()

    if lower_name.endswith(".gz") or file.content_type == "application/gzip":
        detected_type = "gzip"
    elif (file.content_type or "").startswith("image/"):
        detected_type = "image"
    elif (file.content_type or "").startswith("audio/"):
        detected_type = "audio"
    elif (file.content_type or "").startswith("video/"):
        detected_type = "video"
    elif lower_name.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
        detected_type = "image"
    elif lower_name.endswith((".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus")):
        detected_type = "audio"
    elif lower_name.endswith((".mp4", ".mkv", ".avi", ".mov", ".webm")):
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
    input_path = os.path.join(UPLOAD_DIR, filename)

    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    if (
        file_type not in SUPPORTED_ALGORITHMS
        or mode not in SUPPORTED_ALGORITHMS[file_type]
    ):
        raise HTTPException(status_code=400, detail="Tipo o modo de compresión no soportado")

    if algorithm not in SUPPORTED_ALGORITHMS[file_type][mode]:
        raise HTTPException(status_code=400, detail="Algoritmo no compatible")

    base_name, ext = os.path.splitext(filename)
    output_filename = None
    output_path = None

    try:
        if file_type == "image":
            img = PILImage.open(input_path)
            if mode == "lossless" and algorithm == "webp":
                output_filename = f"{base_name}_lossless.webp"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                img.save(output_path, "WEBP", lossless=True, method=6)
            elif mode == "lossless" and algorithm == "png":
                output_filename = f"{base_name}_lossless.png"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                img.save(output_path, "PNG", optimize=True)
            elif mode == "lossy" and algorithm == "jpeg":
                output_filename = f"{base_name}_lossy.jpg"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(output_path, "JPEG", quality=50, optimize=True, progressive=True)
            elif mode == "lossy" and algorithm == "webp":
                output_filename = f"{base_name}_lossy.webp"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                img.save(output_path, "WEBP", quality=50, method=6)

        elif file_type == "audio":
            if mode == "lossless" and algorithm == "flac":
                output_filename = f"{base_name}_lossless.flac"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, acodec="flac", compression_level=8).global_args("-y").run(cmd=ffmpeg_path)
            elif mode == "lossless" and algorithm == "alac":
                output_filename = f"{base_name}_lossless_alac.m4a"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, acodec="alac").global_args("-y").run(cmd=ffmpeg_path)
            elif mode == "lossy" and algorithm == "mp3":
                output_filename = f"{base_name}_lossy.mp3"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, acodec="libmp3lame", audio_bitrate="64k").global_args("-y").run(cmd=ffmpeg_path)
            elif mode == "lossy" and algorithm == "opus":
                output_filename = f"{base_name}_lossy.opus"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, acodec="libopus", audio_bitrate="64k").global_args("-y").run(cmd=ffmpeg_path)

        elif file_type == "video":
            if mode == "lossless" and algorithm == "h264":
                output_filename = f"{base_name}_lossless.mkv"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, vcodec="libx264", crf=0, acodec="copy").global_args("-y").run(cmd=ffmpeg_path)
            elif mode == "lossy" and algorithm == "h264":
                output_filename = f"{base_name}_lossy_h264.mp4"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, vcodec="libx264", crf=28, acodec="aac", audio_bitrate="96k").global_args("-y").run(cmd=ffmpeg_path)
            elif mode == "lossy" and algorithm == "vp9":
                output_filename = f"{base_name}_lossy_vp9.webm"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                ffmpeg.input(input_path).output(output_path, vcodec="libvpx-vp9", crf=32, **{"b:v": "0", "b:a": "96k"}, acodec="libopus").global_args("-y").run(cmd=ffmpeg_path)

        elif file_type == "text":
            with open(input_path, "rb") as input_file:
                content = input_file.read()

            if mode == "lossless" and algorithm == "zlib":
                compressed_data = zlib.compress(content, level=9)
                output_filename = f"{base_name}_lossless.zlib"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with open(output_path, "wb") as output_file:
                    output_file.write(compressed_data)
            elif mode == "lossless" and algorithm == "gzip":
                output_filename = f"{base_name}_lossless.gz"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with gzip.open(output_path, "wb", compresslevel=9) as output_file:
                    output_file.write(content)
            elif mode == "lossless" and algorithm == "bz2":
                compressed_data = bz2.compress(content, compresslevel=9)
                output_filename = f"{base_name}_lossless.bz2"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with open(output_path, "wb") as output_file:
                    output_file.write(compressed_data)
            elif mode == "lossless" and algorithm == "lzma":
                compressed_data = lzma.compress(content, preset=9)
                output_filename = f"{base_name}_lossless.xz"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with open(output_path, "wb") as output_file:
                    output_file.write(compressed_data)
            elif mode == "lossy" and algorithm == "normalize":
                text_str = content.decode("utf-8", errors="ignore")
                lossy_text = " ".join(text_str.split())
                output_filename = f"{base_name}_lossy.txt"
                output_path = os.path.join(UPLOAD_DIR, output_filename)
                with open(output_path, "w", encoding="utf-8") as output_file:
                    output_file.write(lossy_text)

        if output_path is None or not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="No se pudo generar el archivo comprimido")

        original_size = os.path.getsize(input_path)
        generated_size = os.path.getsize(output_path)

        skipped = False
        effective_algorithm = algorithm

        if generated_size >= original_size:
            os.remove(output_path)
            output_filename = filename
            output_path = input_path
            skipped = True
            effective_algorithm = "original_conservado"

        metrics = build_metrics(input_path, output_path, file_type)
        report_filename = f"{base_name}_informe.pdf"

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

        preview_supported = not (file_type == "text" and mode == "lossless" and not skipped)

        return {
            "output_filename": output_filename,
            "output_url": f"/temp/{output_filename}",
            "original_size": metrics["original_size"],
            "compressed_size": metrics["compressed_size"],
            "attempted_size": generated_size,
            "reduction_percent": metrics["reduction_percent"],
            "compression_ratio": metrics["compression_ratio"],
            "metrics": metrics,
            "algorithm": effective_algorithm,
            "skipped": skipped,
            "preview_supported": preview_supported,
            "report_filename": report_filename,
            "report_url": f"/download/{report_filename}"
        }

    except HTTPException:
        raise
    except ffmpeg.Error as error:
        details = error.stderr.decode("utf-8", errors="ignore") if error.stderr else str(error)
        raise HTTPException(status_code=500, detail=("FFmpeg no pudo procesar el archivo: " + details[-1500:]))
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/decompress-gzip")
async def decompress_gzip(filename: str = Form(...)):
    filename = safe_filename(filename)
    input_path = os.path.join(UPLOAD_DIR, filename)

    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail="Archivo GZIP no encontrado")

    if not filename.lower().endswith(".gz"):
        raise HTTPException(status_code=400, detail="El archivo no tiene extensión .gz")

    base_name = filename[:-3]
    root, original_ext = os.path.splitext(base_name)

    output_filename = f"{root}_decompressed{original_ext}" if original_ext else f"{base_name}_decompressed.txt"
    output_path = os.path.join(UPLOAD_DIR, output_filename)

    try:
        with gzip.open(input_path, "rb") as compressed_file:
            data = compressed_file.read()

        with open(output_path, "wb") as output_file:
            output_file.write(data)

        return {
            "output_filename": output_filename,
            "output_url": f"/temp/{output_filename}",
            "original_size": os.path.getsize(input_path),
            "decompressed_size": len(data),
            "preview_type": "text"
        }
    except (gzip.BadGzipFile, OSError, EOFError) as error:
        raise HTTPException(status_code=400, detail=(f"El archivo GZIP no es válido o está dañado: {error}"))


@app.get("/download/{filename}")
async def download_file(filename: str):
    filename = safe_filename(filename)
    file_path = os.path.join(UPLOAD_DIR, filename)

    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)

    raise HTTPException(status_code=404, detail="Archivo no encontrado")