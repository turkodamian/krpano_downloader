# krpanoDownloader

Descargador de panoramas 360 desde 360cities.net y otros sitios que usan krpano.

## Características

- Descarga tiles de cubemap desde CDN de 360gigapixels/cloudflare
- Detecta automáticamente el grid de tiles disponibles
- Maneja tiles de tamaños variables correctamente
- Convierte cubemap a formato equirectangular
- Sin franjas negras ni artefactos

## Uso

```bash
pip install pillow numpy requests

python krpano_downloader.py
```

## Scripts

- `krpano_downloader.py` - Script principal para descargar panoramas
- Modifica `BASE_URL` con la URL del panorama que quieres descargar

## Ejemplo

El script descarga el panorama de Panama Balboa Avenue:
- Resolución: 6000x3000 píxeles
- 6 caras de cubo de 1500x1500 cada una
- Formato de salida: JPEG equirectangular

## Requisitos

- Python 3.8+
- Pillow
- NumPy
- Requests

## Notas

- La resolución máxima depende de lo que esté disponible públicamente en el CDN
- Algunos panoramas pueden requerir cuenta o licencia para mayor resolución
