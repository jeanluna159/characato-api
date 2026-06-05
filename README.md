# Characato Store - Premium Catalog API

API que recibe una foto de producto y devuelve una imagen profesional lista para catálogo: fondo limpio, colores mejorados, sombra suave y logo de Characato.

## Estructura del proyecto

```
characato-api/
├── main.py              # Código principal de la API
├── requirements.txt     # Librerías de Python
├── render.yaml          # Configuración de despliegue
└── assets/
    └── logo_circular_de_characato_arequipa.png   ← agregar aquí
```

## Antes de subir a Render

1. Coloca tu logo dentro de `assets/` con el nombre exacto:
   `logo_circular_de_characato_arequipa.png`
2. (Opcional) Agrega un patrón de fondo como:
   `patron_sutil_de_marca_characato_store.png`

## Endpoints

- `GET /` → verificación de que la API está viva
- `POST /premium` → recibe una imagen, devuelve URL de la versión procesada

## Despliegue en Render

1. Sube esta carpeta a un repositorio en GitHub
2. En Render: New → Web Service → conectar el repo
3. Render detecta el archivo `render.yaml` y configura todo solo
4. Espera ~5-10 minutos al primer build (rembg descarga su modelo)
5. Render te dará una URL como: `https://characato-api.onrender.com`
