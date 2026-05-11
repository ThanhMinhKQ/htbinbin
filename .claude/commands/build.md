# Build / Start

## Local app

```bash
uvicorn app.main:app --reload
```

## Notes

- App requires environment variables from `.env`, especially `DATABASE_URL`.
- Static files are served from `app/static`.
- Uploads are served from `uploads`.
