web: python -m gunicorn receiptmanager.asgi:application -k uvicorn.workers.UvicornWorker
worker: celery -A receiptmanager worker --loglevel=info -P gevent -Q default,maintenance,monitoring,ai_batch,ai_processing,cache
beat: celery -A receiptmanager beat --loglevel=info
