# Compresor Multimedia y de Texto

Aplicación web desarrollada con **FastAPI** para comprimir y descomprimir archivos multimedia desde una interfaz web.

El proyecto permite ejecutar la aplicación de dos maneras:

1. **Con Docker:** entorno aislado y configuración simplificada.
2. **Sin Docker:** instalación y ejecución directamente en Windows con Python.

## Tecnologías utilizadas

- Python
- FastAPI
- Uvicorn
- Jinja2
- Pillow
- FFmpeg
- `ffmpeg-python`
- `imageio-ffmpeg`

## Estructura del proyecto

```text
proyecto/
├── main.py
├── requirements.txt
├── Dockerfile
├── .dockerignore
├── .gitignore
├── README.md
└── templates/
    └── index.html
```

La aplicación puede crear el directorio `temp/` para almacenar archivos temporales y resultados.

---

# Opción 1: Ejecutar con Docker

Esta opción permite ejecutar el proyecto en un contenedor sin instalar las dependencias de Python directamente en el sistema.

## Requisitos

- Windows 10 u 11.
- [Docker Desktop](https://www.docker.com/products/docker-desktop/).
- WSL 2 habilitado si se utiliza el motor de Docker basado en WSL 2.

### 1. Instalar Docker Desktop

Descarga Docker Desktop desde la [página oficial](https://www.docker.com/products/docker-desktop/), instálalo y ejecútalo.

Si WSL 2 no está instalado, abre PowerShell como administrador y ejecuta:

```powershell
wsl --install
```

Reinicia el equipo si se solicita y abre Docker Desktop.

Comprueba que Docker funciona:

```powershell
docker --version
docker info
```

### 2. Construir la imagen

Abre PowerShell en la carpeta raíz del proyecto, donde se encuentra el archivo `Dockerfile`, y ejecuta:

```powershell
docker build -t multimedia-compressor .
```

Este comando construye la imagen con las dependencias necesarias.

### 3. Iniciar el contenedor

Ejecuta:

```powershell
docker run --name multimedia-web -p 8000:8000 multimedia-compressor
```

La aplicación estará disponible en:

- **Aplicación web:** http://localhost:8000
- **Documentación de la API:** http://localhost:8000/docs

Para conservar los archivos generados en la carpeta `temp/` del proyecto, puedes iniciar el contenedor con un volumen:

```powershell
docker run --name multimedia-web -p 8000:8000 -v "${PWD}/temp:/app/temp" multimedia-compressor
```

> Ejecuta una sola de las dos variantes anteriores. Si ya existe un contenedor con el nombre `multimedia-web`, elimínalo antes de crearlo de nuevo.

### 4. Administrar el contenedor

Detener el contenedor:

```powershell
docker stop multimedia-web
```

Volver a iniciarlo:

```powershell
docker start multimedia-web
```

Consultar los registros:

```powershell
docker logs -f multimedia-web
```

Eliminar el contenedor:

```powershell
docker rm -f multimedia-web
```

Si modificas el código y quieres incorporar los cambios, vuelve a construir la imagen y crea un contenedor nuevo.

---

# Opción 2: Ejecutar sin Docker

Esta opción ejecuta la aplicación directamente en Windows utilizando Python y un entorno virtual.

## Requisitos

- Python instalado.
- `pip`, incluido normalmente con Python.
- FFmpeg disponible mediante `imageio-ffmpeg` o instalado en el sistema, según la configuración utilizada por la aplicación.

Puedes descargar