from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps, ImageEnhance
from typing import Optional
import httpx
import base64
import io
import uuid

app = FastAPI(title="Characato Store Premium Catalog API")

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(exist_ok=True)

LOGO_PATH = ASSETS_DIR / "logo_circular_de_characato_arequipa.png"
PATTERN_PATH = ASSETS_DIR / "patron_sutil_de_marca_characato_store.png"

app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")


# --- LAZY LOADING de rembg ---
_remove_fn = None

def remove_background(img):
    global _remove_fn
    if _remove_fn is None:
        from rembg import remove
        _remove_fn = remove
    return _remove_fn(img)


class ImageRequest(BaseModel):
    image_url: Optional[str] = None
    image_base64: Optional[str] = None


def set_opacity(img: Image.Image, opacity: float) -> Image.Image:
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    a = a.point(lambda p: int(p * opacity))
    img.putalpha(a)
    return img


def crop_transparent(img: Image.Image, padding: int = 40) -> Image.Image:
    img = img.convert("RGBA")
    bbox = img.getbbox()
    if not bbox:
        return img
    left, top, right, bottom = bbox
    left = max(left - padding, 0)
    top = max(top - padding, 0)
    right = min(right + padding, img.width)
    bottom = min(bottom + padding, img.height)
    return img.crop((left, top, right, bottom))


def enhance_product(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img, mask=img.getchannel("A"))
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.25)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.08)
    rgb = ImageEnhance.Color(rgb).enhance(1.05)
    final = rgb.convert("RGBA")
    final.putalpha(img.getchannel("A"))
    return final


def create_soft_background(width: int, height: int) -> Image.Image:
    bg = Image.new("RGBA", (width, height), (248, 248, 246, 255))
    if PATTERN_PATH.exists():
        pattern = Image.open(PATTERN_PATH).convert("RGBA")
        pattern = ImageOps.fit(pattern, (width, height), method=Image.LANCZOS)
        pattern = set_opacity(pattern, 0.16)
        bg.alpha_composite(pattern)
    return bg


def add_shadow(canvas: Image.Image, product: Image.Image, x: int, y: int) -> None:
    alpha = product.getchannel("A")
    shadow = Image.new("RGBA", product.size, (0, 0, 0, 0))
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(18))
    shadow_alpha = shadow_alpha.point(lambda p: int(p * 0.22))
    shadow.putalpha(shadow_alpha)
    shadow_y = y + 18
    canvas.alpha_composite(shadow, (x, shadow_y))


def add_logo(canvas: Image.Image) -> None:
    if not LOGO_PATH.exists():
        return
    width, height = canvas.size
    logo = Image.open(LOGO_PATH).convert("RGBA")
    max_logo_width = int(width * 0.22)
    max_logo_height = int(height * 0.22)
    logo.thumbnail((max_logo_width, max_logo_height), Image.LANCZOS)
    logo = set_opacity(logo, 0.58)
    margin = int(width * 0.035)
    x = width - logo.width - margin
    y = margin
    canvas.alpha_composite(logo, (x, y))


def process_image_bytes(raw: bytes, base_url: str) -> dict:
    try:
        original = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer la imagen.")

    # 1. Quitar fondo
    try:
        product = remove_background(original)
        if isinstance(product, bytes):
            product = Image.open(io.BytesIO(product)).convert("RGBA")
        else:
            product = product.convert("RGBA")
    except Exception:
        product = original

    # 2. Recortar y mejorar
    product = crop_transparent(product, padding=35)
    product = enhance_product(product)

    # 3. Crear lienzo
    canvas_w, canvas_h = 1600, 1200
    canvas = create_soft_background(canvas_w, canvas_h)

    # 4. Escalar producto
    max_product_w = int(canvas_w * 0.72)
    max_product_h = int(canvas_h * 0.72)
    product.thumbnail((max_product_w, max_product_h), Image.LANCZOS)
    x = (canvas_w - product.width) // 2
    y = int(canvas_h * 0.52 - product.height / 2)

    # 5. Sombra y producto
    add_shadow(canvas, product, x, y)
    canvas.alpha_composite(product, (x, y))

    # 6. Logo
    add_logo(canvas)

    # 7. Guardar
    filename = f"characato_premium_{uuid.uuid4().hex}.png"
    output_path = OUTPUTS_DIR / filename
    canvas.save(output_path, "PNG")
    image_url = f"{base_url}/outputs/{filename}"

    return {"status": "ok", "format": "png", "image_url": image_url}


@app.get("/")
def root():
    return {"status": "ok", "service": "Characato Store Premium Catalog API"}


@app.post("/premium")
async def create_premium_image(request: Request, file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="El archivo debe ser una imagen.")
    raw = await file.read()
    base_url = str(request.base_url).rstrip("/")
    result = process_image_bytes(raw, base_url)
    return JSONResponse(result)


@app.post("/premium-url")
async def create_premium_image_from_url(request: Request, body: ImageRequest):
    """Endpoint para GPT Actions: acepta URL o base64."""
    raw = None

    # Opcion 1: base64
    if body.image_base64:
        try:
            # Limpiar prefijo data:image/...;base64, si existe
            b64 = body.image_base64
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(status_code=400, detail="No se pudo decodificar la imagen base64.")

    # Opcion 2: URL publica
    elif body.image_url:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(body.image_url)
                response.raise_for_status()
                raw = response.content
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo descargar la imagen: {str(e)}")

    if not raw:
        raise HTTPException(status_code=400, detail="Envía image_base64 o image_url.")

    base_url = str(request.base_url).rstrip("/")
    result = process_image_bytes(raw, base_url)
    return JSONResponse(result)
