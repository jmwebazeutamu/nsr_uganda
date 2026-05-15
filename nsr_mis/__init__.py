"""Importing the Celery app at package load makes @shared_task
discoverable across the project — Django and Celery's normal handshake
per the Celery docs."""
from .celery import app as celery_app

__all__ = ("celery_app",)
