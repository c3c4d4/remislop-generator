from celery import Celery
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

task_always_eager = os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() in {"1", "true", "yes"}
broker_url = os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@rabbitmq:5672//")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "rpc://")

if task_always_eager:
    broker_url = "memory://"
    result_backend = "cache+memory://"

celery_app = Celery(
    __name__,
    broker=broker_url,
    backend=result_backend,
    include=['tasks']
)

# You can also add other Celery configurations here
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],  # Ignore other content
    result_serializer='json',
    timezone='Europe/London',
    enable_utc=True,
    task_always_eager=task_always_eager,
    task_store_eager_result=task_always_eager,
    task_eager_propagates=task_always_eager,
)

# Ensure the logger is configured for use in Celery tasks
celery_app.log.setup_task_loggers()

# Export the logger so it can be imported in other modules
__all__ = ['celery_app', 'logger']
