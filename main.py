from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps, ImageEnhance
from typing import Optional
import httpx
import base64
import io
import uuid

app = FastAPI(title="Characato Store Premium Catalog API")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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


def set_opacity(img, opacity):
    img = img.convert("RGBA")
    r, g, b, a = img.split()
    a = a.point(lambda p: int(p * opacity))
    img.putalpha(a)
    return img


def crop_transparent(img, padding=40):
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


def enhance_product(img):
    img = img.convert("RGBA")
    rgb = Image.new("RGB", img.size, (255, 255, 255))
    rgb.paste(img, mask=img.getchannel("A"))
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.25)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.08)
    rgb = ImageEnhance.Color(rgb).enhance(1.05)
    final = rgb.convert("RGBA")
    final.putalpha(img.getchannel("A"))
    return final


def create_soft_background(width, height):
    bg = Image.new("RGBA", (width, height), (248, 248, 246, 255))
    if PATTERN_PATH.exists():
        pattern = Image.open(PATTERN_PATH).convert("RGBA")
        pattern = ImageOps.fit(pattern, (width, height), method=Image.LANCZOS)
        pattern = set_opacity(pattern, 0.16)
        bg.alpha_composite(pattern)
    return bg


def add_shadow(canvas, product, x, y):
    alpha = product.getchannel("A")
    shadow = Image.new("RGBA", product.size, (0, 0, 0, 0))
    shadow_alpha = alpha.filter(ImageFilter.GaussianBlur(18))
    shadow_alpha = shadow_alpha.point(lambda p: int(p * 0.22))
    shadow.putalpha(shadow_alpha)
    canvas.alpha_composite(shadow, (x, y + 18))


def add_logo(canvas):
    if not LOGO_PATH.exists():
        return
    width, height = canvas.size
    logo = Image.open(LOGO_PATH).convert("RGBA")
    max_logo_w = int(width * 0.22)
    max_logo_h = int(height * 0.22)
    logo.thumbnail((max_logo_w, max_logo_h), Image.LANCZOS)
    logo = set_opacity(logo, 0.58)
    margin = int(width * 0.035)
    canvas.alpha_composite(logo, (width - logo.width - margin, margin))


def process_image_bytes(raw, base_url):
    try:
        original = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        raise HTTPException(status_code=400, detail="No se pudo leer la imagen.")
    try:
        product = remove_background(original)
        if isinstance(product, bytes):
            product = Image.open(io.BytesIO(product)).convert("RGBA")
        else:
            product = product.convert("RGBA")
    except Exception:
        product = original
    product = crop_transparent(product, padding=35)
    product = enhance_product(product)
    canvas_w, canvas_h = 1600, 1200
    canvas = create_soft_background(canvas_w, canvas_h)
    max_pw = int(canvas_w * 0.72)
    max_ph = int(canvas_h * 0.72)
    product.thumbnail((max_pw, max_ph), Image.LANCZOS)
    x = (canvas_w - product.width) // 2
    y = int(canvas_h * 0.52 - product.height / 2)
    add_shadow(canvas, product, x, y)
    canvas.alpha_composite(product, (x, y))
    add_logo(canvas)
    filename = f"characato_premium_{uuid.uuid4().hex}.png"
    output_path = OUTPUTS_DIR / filename
    canvas.save(output_path, "PNG")
    return {"status": "ok", "format": "png", "image_url": f"{base_url}/outputs/{filename}"}


@app.get("/")
def root():
    return {"status": "ok", "service": "Characato Store Premium Catalog API"}


@app.get("/editor", response_class=HTMLResponse)
def editor():
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Characato Store — Editor de Catálogo</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Source+Sans+3:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{--tierra:#C4752B;--tierra-dark:#9B5A1E;--verde:#2D5A3D;--crema:#F8F8F6;--gris:#E8E6E2;--texto:#2C2C2C;--texto-light:#6B6B6B}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Source Sans 3',sans-serif;background:var(--crema);color:var(--texto);min-height:100vh}
.header{text-align:center;padding:40px 20px 20px}
.header h1{font-family:'Playfair Display',serif;font-size:2rem;color:var(--verde)}
.header p{color:var(--texto-light);margin-top:8px;font-size:1.05rem}
.container{max-width:900px;margin:0 auto;padding:20px}
.upload-zone{border:2px dashed var(--tierra);border-radius:16px;padding:50px 30px;text-align:center;cursor:pointer;transition:all .3s;background:#fff;position:relative}
.upload-zone:hover{border-color:var(--verde);background:#f0f5f1}
.upload-zone.drag-over{border-color:var(--verde);background:#e8f0ea;transform:scale(1.01)}
.upload-zone.has-preview{padding:20px}
.upload-icon{font-size:3rem;margin-bottom:16px}
.upload-zone h3{font-family:'Playfair Display',serif;font-size:1.3rem;color:var(--verde);margin-bottom:8px}
.upload-zone p{color:var(--texto-light);font-size:.95rem}
.upload-zone input[type=file]{position:absolute;inset:0;opacity:0;cursor:pointer}
.preview-container{display:none;margin-top:10px}
.preview-container.visible{display:block}
.preview-img{max-width:100%;max-height:300px;border-radius:12px;display:block;margin:0 auto}
.file-name{text-align:center;margin-top:8px;color:var(--texto-light);font-size:.85rem}
.btn-process{display:none;width:100%;margin-top:24px;padding:16px;font-family:'Source Sans 3',sans-serif;font-size:1.1rem;font-weight:600;color:#fff;background:var(--tierra);border:none;border-radius:12px;cursor:pointer;transition:all .3s}
.btn-process.visible{display:block}
.btn-process:hover{background:var(--tierra-dark);transform:translateY(-1px)}
.btn-process:disabled{background:var(--gris);color:var(--texto-light);cursor:not-allowed;transform:none}
.status{display:none;text-align:center;margin-top:20px;padding:16px;border-radius:12px;font-size:.95rem}
.status.visible{display:block}
.status.loading{background:#FFF8F0;color:var(--tierra);border:1px solid #F0D9B5}
.status.error{background:#FFF0F0;color:#C0392B;border:1px solid #F0B5B5}
.status.success{background:#F0F8F0;color:var(--verde);border:1px solid #B5D9B5}
.spinner{display:inline-block;width:18px;height:18px;border:2px solid var(--tierra);border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:8px}
@keyframes spin{to{transform:rotate(360deg)}}
.result{display:none;margin-top:30px;background:#fff;border-radius:16px;padding:20px;box-shadow:0 4px 20px rgba(0,0,0,.06)}
.result.visible{display:block}
.result h3{font-family:'Playfair Display',serif;color:var(--verde);margin-bottom:16px;text-align:center}
.comparison{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.comparison-box{text-align:center}
.comparison-box img{max-width:100%;max-height:280px;border-radius:10px}
.comparison-box .label{font-size:.8rem;color:var(--texto-light);margin-top:6px;text-transform:uppercase;letter-spacing:.1em}
.btn-download{display:block;width:100%;margin-top:16px;padding:14px;font-family:'Source Sans 3',sans-serif;font-size:1rem;font-weight:600;color:#fff;background:var(--verde);border:none;border-radius:12px;cursor:pointer;transition:all .3s;text-decoration:none;text-align:center}
.btn-download:hover{background:#1E4A2E}
.btn-new{display:block;width:100%;margin-top:10px;padding:14px;font-family:'Source Sans 3',sans-serif;font-size:1rem;font-weight:600;color:var(--tierra);background:transparent;border:2px solid var(--tierra);border-radius:12px;cursor:pointer;transition:all .3s}
.btn-new:hover{background:#FFF8F0}
.footer{text-align:center;padding:40px 20px;color:var(--texto-light);font-size:.85rem}
@media(max-width:600px){.comparison{grid-template-columns:1fr}.header h1{font-size:1.5rem}}
</style>
</head>
<body>
<div class="header"><h1>Characato Store</h1><p>Editor de Catálogo Premium</p></div>
<div class="container">
<div class="upload-zone" id="uploadZone">
<div id="uploadContent"><div class="upload-icon">📸</div><h3>Sube tu foto de producto</h3><p>Arrastra una imagen aquí o haz clic para seleccionar</p><p style="margin-top:6px;font-size:.8rem;color:#999">JPG, PNG o WEBP · Máximo 10 MB</p></div>
<div class="preview-container" id="previewContainer"><img class="preview-img" id="previewImg"><p class="file-name" id="fileName"></p></div>
<input type="file" id="fileInput" accept="image/jpeg,image/png,image/webp">
</div>
<button class="btn-process" id="btnProcess" onclick="processImage()">Procesar imagen</button>
<div class="status" id="status"></div>
<div class="result" id="result">
<h3>Resultado</h3>
<div class="comparison"><div class="comparison-box"><img id="originalThumb"><div class="label">Original</div></div><div class="comparison-box"><img id="resultImg"><div class="label">Procesada</div></div></div>
<a class="btn-download" id="btnDownload" download="characato_premium.png">Descargar imagen</a>
<button class="btn-new" onclick="resetAll()">Procesar otra imagen</button>
</div>
</div>
<div class="footer">Characato Store · Arequipa, Perú</div>
<script>
const API_URL=window.location.origin;
const uploadZone=document.getElementById('uploadZone'),fileInput=document.getElementById('fileInput'),previewContainer=document.getElementById('previewContainer'),previewImg=document.getElementById('previewImg'),fileName=document.getElementById('fileName'),uploadContent=document.getElementById('uploadContent'),btnProcess=document.getElementById('btnProcess'),status=document.getElementById('status'),result=document.getElementById('result');
let selectedFile=null;
uploadZone.addEventListener('dragover',e=>{e.preventDefault();uploadZone.classList.add('drag-over')});
uploadZone.addEventListener('dragleave',()=>uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop',e=>{e.preventDefault();uploadZone.classList.remove('drag-over');if(e.dataTransfer.files.length)handleFile(e.dataTransfer.files[0])});
fileInput.addEventListener('change',e=>{if(e.target.files.length)handleFile(e.target.files[0])});
function handleFile(file){if(!file.type.startsWith('image/')){showStatus('El archivo debe ser una imagen.','error');return}if(file.size>10*1024*1024){showStatus('La imagen es muy grande. Máximo 10 MB.','error');return}selectedFile=file;const reader=new FileReader();reader.onload=e=>{previewImg.src=e.target.result;fileName.textContent=file.name+' ('+(file.size/1024/1024).toFixed(1)+' MB)';uploadContent.style.display='none';previewContainer.classList.add('visible');uploadZone.classList.add('has-preview');btnProcess.classList.add('visible');status.classList.remove('visible');result.classList.remove('visible')};reader.readAsDataURL(file)}
async function processImage(){if(!selectedFile)return;btnProcess.disabled=true;btnProcess.textContent='Procesando...';showStatus('<span class="spinner"></span> Procesando imagen. La primera vez puede tardar hasta 2 minutos...','loading');result.classList.remove('visible');const formData=new FormData();formData.append('file',selectedFile);try{const response=await fetch(API_URL+'/premium',{method:'POST',body:formData});if(!response.ok){const err=await response.json().catch(()=>({}));throw new Error(err.detail||'Error del servidor')}const data=await response.json();if(data.status==='ok'&&data.image_url){showStatus('Imagen procesada con éxito.','success');document.getElementById('originalThumb').src=previewImg.src;document.getElementById('resultImg').src=data.image_url;document.getElementById('btnDownload').href=data.image_url;result.classList.add('visible')}else{throw new Error('Respuesta inesperada')}}catch(err){showStatus('Error: '+err.message+'. Intenta de nuevo.','error')}btnProcess.disabled=false;btnProcess.textContent='Procesar imagen'}
function showStatus(msg,type){status.innerHTML=msg;status.className='status visible '+type}
function resetAll(){selectedFile=null;fileInput.value='';previewContainer.classList.remove('visible');uploadContent.style.display='';uploadZone.classList.remove('has-preview');btnProcess.classList.remove('visible');status.classList.remove('visible');result.classList.remove('visible')}
</script>
</body>
</html>"""


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
    raw = None
    if body.image_base64:
        try:
            b64 = body.image_base64
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            raw = base64.b64decode(b64)
        except Exception:
            raise HTTPException(status_code=400, detail="No se pudo decodificar la imagen base64.")
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
