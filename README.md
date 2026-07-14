# GHAZA COMPUTER Backend

Django REST Framework backend foundation for laptop spare parts inventory, POS/direct sales, quotations, purchases, GRN receiving, finance, branches, HRMS, document expiry monitoring, transfers, shipment tracking, notifications, audit logs, and reports.

## Stack
Python 3.12, Django, DRF, PostgreSQL, Simple JWT, Celery, Redis, Docker, drf-spectacular.

## Quick start with Docker
```bash
cp .env.example .env
docker compose up --build
docker compose exec backend python manage.py seed_data
```

Open Swagger: `http://localhost:8000/api/docs/`  
OpenAPI schema: `http://localhost:8000/api/schema/`  
Admin: `http://localhost:8000/admin/`

Starter admin login: `admin@ghazacomputer.local` / `Admin@123`

## Local setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements/development.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

Run background jobs:
```bash
celery -A config worker -l info
celery -A config beat -l info
```

## Main workflows
- Confirm invoice → validates inventory, deducts stock, creates stock movement and receivable ledger entry.
- Confirm GRN → increases branch stock and creates stock movements.
- Dispatch / receive transfer → moves stock across branches.
- Employee expiry task → runs daily via Celery Beat and creates notifications for document expiry windows.

## Notes
This is a production-oriented foundation. Before production deployment, add database migrations to source control, configure email/S3 storage, tighten CORS and security settings, complete report export templates, and add test coverage for every approval/payment workflow.
