# Compresor Multimedia y de Texto

Aplicación web desarrollada con **FastAPI** para comprimir y descomprimir archivos de texto y multimedia desde una interfaz web.

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

Puedes descargar Python desde la [página oficial](https://www.python.org/downloads/).

Durante la instalación en Windows, activa la opción **Add Python to PATH**.

Comprueba la instalación desde PowerShell:

```powershell
python --version
pip --version
```

Si el comando `python` no funciona, prueba:

```powershell
py --version
```

### 1. Abrir la carpeta del proyecto

Abre PowerShell en el directorio donde se encuentra `main.py`.

Por ejemplo:

```powershell
cd C:\ruta\al\proyecto
```

Sustituye la ruta por la ubicación real del proyecto.

### 2. Crear un entorno virtual

Ejecuta:

```powershell
python -m venv .venv
```

### 3. Activar el entorno virtual

En PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Si PowerShell impide la activación por la política de ejecución, puedes activar el entorno desde CMD con:

```cmd
.venv\Scripts\activate.bat
```

### 4. Instalar las dependencias

Instala los paquetes definidos en `requirements.txt`:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

El archivo `requirements.txt` debe incluir las dependencias utilizadas por el proyecto, como:

```text
fastapi
uvicorn[standard]
python-multipart
jinja2
Pillow
ffmpeg-python
imageio-ffmpeg
```

Si el archivo ya contiene otras dependencias necesarias, consérvalas.

### 5. Ejecutar la aplicación

Inicia el servidor con:

```powershell
uvicorn main:app --reload
```

La aplicación estará disponible en:

- **Aplicación web:** http://localhost:8000
- **Documentación de la API:** http://localhost:8000/docs

El parámetro `--reload` reinicia el servidor cuando detecta cambios en el código. Es útil durante el desarrollo.

Para detener el servidor, pulsa `Ctrl + C` en la terminal.

### 6. Desactivar el entorno virtual

Cuando termines, puedes ejecutar:

```powershell
deactivate
```

---

## Solución de problemas

| Problema | Solución |
|---|---|
| `docker` no se reconoce como comando | Comprueba que Docker Desktop está instalado y en ejecución; abre una terminal nueva. |
| No se puede conectar con Docker | Inicia Docker Desktop y espera a que el motor esté listo. |
| `uvicorn` no se reconoce | Activa el entorno virtual y ejecuta `python -m pip install -r requirements.txt`. |
| Error al instalar dependencias | Comprueba la versión de Python y revisa el mensaje de error de `pip`. |
| Error relacionado con FFmpeg | Comprueba que `imageio-ffmpeg` esté instalado y que el código obtenga correctamente el ejecutable de FFmpeg. |
| El puerto 8000 ya está ocupado | Utiliza otro puerto, por ejemplo `uvicorn main:app --reload --port 8001`, o cambia el mapeo de puertos de Docker. |
| No aparecen los archivos generados | Comprueba la ruta de almacenamiento y, si utilizas Docker, el montaje del volumen. |

## ¿Qué opción elegir?

| Característica | Con Docker | Sin Docker |
|---|---|---|
| Instalación de dependencias | Dentro de la imagen | En el entorno virtual |
| Configuración inicial | Requiere Docker Desktop | Requiere Python |
| Aislamiento del entorno | Sí | Parcial, mediante entorno virtual |
| Desarrollo y depuración | Posible | Directo y sencillo |
| Reproducibilidad entre equipos | Generalmente mayor | Depende del entorno local |

**Recomendación:** utiliza Docker para ejecutar el proyecto en un entorno reproducible y facilitar su despliegue. Utiliza la ejecución sin Docker si vas a modificar y depurar el código con frecuencia.

## Seguridad

Antes de publicar la aplicación en Internet:

- Limita el tamaño y los tipos de archivo que se pueden subir.
- Valida los nombres de archivo y las rutas de almacenamiento.
- Configura una política de limpieza para los archivos temporales.
- Evita exponer archivos subidos o resultados a usuarios no autorizados.
- No utilices la configuración de desarrollo como configuración de producción sin revisar sus medidas de seguridad.
