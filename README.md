# Mekko Backend

FastAPI-backend for Mekko-appen. Proxyer kall til Statens Vegvesen sin
Kjøretøyopplysninger-API, og er fundamentet for fremtidige funksjoner
(autentisering, AI-mekaniker, service-historikk).

## Lokal kjøring

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# legg inn VEGVESENET_API_KEY i .env

uvicorn app.main:app --reload
```

API tilgjengelig på http://localhost:8000. Swagger UI: http://localhost:8000/docs

### Test endpoint

```bash
curl "http://localhost:8000/api/v1/cars/lookup?plate=KH75443"
```

## Endpoints

| Metode | Path                              | Beskrivelse                       |
|--------|-----------------------------------|-----------------------------------|
| GET    | `/`                               | Health/info                       |
| GET    | `/health`                         | Healthcheck for Railway           |
| GET    | `/api/v1/cars/lookup?plate=XXX`   | Slå opp bil i Vegvesenet          |

## Deploy til Railway

1. Pusher koden til GitHub
2. Railway → New Project → Deploy from GitHub repo
3. Sett environment variable: `VEGVESENET_API_KEY`
4. Railway oppdager `Procfile` + `requirements.txt` automatisk via nixpacks
5. Public URL blir tilgjengelig under Settings → Networking
