# receiptmanager/celery.py
import os
from celery import Celery
from django.conf import settings

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'receiptmanager.settings')

app = Celery('receiptmanager')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# CRITICAL: Disable file persistence that caches old tasks
app.conf.beat_scheduler = 'celery.beat:PersistentScheduler'
app.conf.beat_schedule_filename = None  # Don't use any file

app.conf.update(
    imports=(
        # Auth service tasks
        'auth_service.tasks',

        # AI service tasks
        'ai_service.tasks.ai_tasks',

        # Receipt service - ONLY MVP-active tasks
        'receipt_service.tasks.active.cleanup_tasks',
        'receipt_service.tasks.active.file_tasks',
    )
)

# Load task modules from all registered Django apps.
# app.autodiscover_tasks()

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
