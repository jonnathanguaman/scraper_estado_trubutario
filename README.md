# Extractor Estado Tributario SRI

API en Python con FastAPI y Playwright para consultar la página pública de Estado Tributario del SRI Ecuador, renderizar la SPA Angular y devolver el HTML final junto con datos estructurados cuando estén disponibles.

La implementación no evade ni resuelve automáticamente reCAPTCHA/F5. Usa una sesión real de navegador con perfil persistente para que un operador pueda resolver controles cuando Google/SRI lo requiera.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m playwright install chromium
```

## Configuración

```powershell
Copy-Item .env.example .env
```

Por defecto `SRI_HEADLESS=false`, para que el navegador sea visible y se pueda resolver reCAPTCHA manualmente si aparece.

## Ejecutar

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Abrir o preparar sesión:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/browser/session/start
```

Consultar:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/estado-tributario/consultar `
  -ContentType application/json `
  -Body '{"identificacion":"1700000000001","tipo":"ruc_cedula","return_html":true,"return_data":true}'
```

## Pruebas

```powershell
pytest
```

