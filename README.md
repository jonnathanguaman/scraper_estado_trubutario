# Extractor Estado Tributario SRI

API FastAPI + Playwright para consultar la pagina publica de Estado Tributario del SRI Ecuador.

La API corre en modo headless por defecto para servidor Linux/Docker. No evade ni resuelve automaticamente reCAPTCHA/F5; si el SRI/Google exige validacion humana, la consulta puede terminar como `captcha_required` o `timeout`.

## Docker Compose en Linux

1. Copia variables de entorno:

```bash
cp .env.example .env
```

2. Levanta el servicio:

```bash
docker compose up -d --build
```

3. Revisa estado:

```bash
docker compose ps
docker compose logs -f extractor-estado-tributario
```

4. Health check:

```bash
curl http://localhost:8000/health
```

5. Consulta:

```bash
curl -X POST http://localhost:8000/api/v1/estado-tributario/consultar \
  -H "Content-Type: application/json" \
  -d '{
    "identificacion": "0106775646001",
    "tipo": "ruc_cedula",
    "return_html": false,
    "return_data": true,
    "screenshot": false
  }'
```

Respuesta esperada cuando la consulta llega a resultados:

```json
{
  "status": "ok",
  "identificacion": "0106775646001",
  "data": {
    "permiso_facturacion": {
      "vigencia": "12 meses"
    },
    "estado_tributario": {
      "resultado": "AL DIA EN SUS OBLIGACIONES"
    }
  }
}
```

## Variables

`.env.example`:

```env
SRI_HEADLESS=true
SRI_TIMEOUT_MS=60000
SRI_PROFILE_DIR=/app/storage/browser-profile
SRI_RATE_LIMIT_SECONDS=5
SRI_SCREENSHOT_DIR=/app/storage/screenshots
```

Puedes cambiar el puerto publico con:

```bash
APP_PORT=8080 docker compose up -d --build
```

## Persistencia

El compose monta:

```text
./storage:/app/storage
```

Alli se conserva el perfil persistente del navegador y screenshots opcionales.

## Desarrollo local

```powershell
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Pruebas

```bash
python -m pytest
```
