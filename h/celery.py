# -*- coding: utf-8 -*-

"""
Celery worker bootstrap and configuration.

This module configures a Celery application for processing background jobs, and
integrates it with the Pyramid application by attaching a bootstrapped fake
"request" object to the application where it can be retrieved by tasks.
"""

from __future__ import absolute_import

from datetime import timedelta
import logging
import os

from celery import Celery
from celery import signals
from celery.utils.log import get_task_logger
from kombu import Exchange, Queue
from raven.contrib.celery import register_signal, register_logger_signal

__all__ = (
    'celery',
    'get_task_logger',
)

log = logging.getLogger(__name__)

celery = Celery('h')
celery.conf.update(
    # Default to using database number 10 so we don't conflict with the session
    # store.
    BROKER_URL=os.environ.get('CELERY_BROKER_URL',
        os.environ.get('BROKER_URL', 'amqp://guest:guest@localhost:5672//')),
    CELERYBEAT_SCHEDULE={
        'delete-expired-authtickets': {
            'task': 'h.auth.worker.delete_expired_auth_tickets',
            'schedule': timedelta(hours=1)
        },
        'delete-expired-tokens': {
            'task': 'h.auth.worker.delete_expired_tokens',
            'schedule': timedelta(hours=1)
        },
    },
    CELERY_ACCEPT_CONTENT=['json'],
    # Enable at-least-once delivery mode. This probably isn't actually what we
    # want for all of our queues, but it makes the failure-mode behaviour of
    # Celery the same as our old NSQ worker:
    CELERY_ACKS_LATE=True,
    CELERY_DISABLE_RATE_LIMITS=True,
    CELERY_IGNORE_RESULT=True,
    CELERY_IMPORTS=(
        'h.auth.worker',
        'h.tasks.admin',
        'h.tasks.indexer',
        'h.tasks.mailer',
        'h.tasks.nipsa',
    ),
    CELERY_ROUTES={
        'h.tasks.indexer.add_annotation': 'indexer',
        'h.tasks.indexer.delete_annotation': 'indexer',
    },
    CELERY_TASK_SERIALIZER='json',
    CELERY_QUEUES=[
        Queue('celery',
              durable=True,
              routing_key='celery',
              exchange=Exchange('celery', type='direct', durable=True)),
        Queue('indexer',
              durable=True,
              routing_key='indexer',
              exchange=Exchange('indexer', type='direct', durable=True)),
    ],
    # Only accept one task at a time. This also probably isn't what we want
    # (especially not for, say, a search indexer task) but it makes the
    # behaviour consistent with the previous NSQ-based worker:
    CELERYD_PREFETCH_MULTIPLIER=1,
)


@signals.worker_init.connect
def bootstrap_worker(sender, **kwargs):
    request = sender.app.webapp_bootstrap()
    sender.app.request = request

    # Configure Sentry reporting on task failure
    register_signal(request.sentry)
    register_logger_signal(request.sentry, loglevel=logging.ERROR)


@signals.task_prerun.connect
def reset_feature_flags(sender, **kwargs):
    """Reset feature flags before running each task."""
    sender.app.request.feature.clear()


@signals.task_success.connect
def transaction_commit(sender, **kwargs):
    """Commit the request transaction after each successful task execution."""
    sender.app.request.tm.commit()


@signals.task_failure.connect
def transaction_abort(sender, **kwargs):
    """Abort the request transaction after each failed task execution."""
    sender.app.request.tm.abort()


def start(argv, bootstrap):
    """Run the Celery CLI."""
    # We attach the bootstrap function directly to the Celery application
    # instance, and it's then used in the worker bootstrap subscriber above.
    celery.webapp_bootstrap = bootstrap
    celery.start(argv)
