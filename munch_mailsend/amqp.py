from django.conf import settings
from kombu import Queue
from kombu import Exchange


def get_queue(connection, name):
    exchange = Exchange(
        channel=connection,
        name=settings.CELERY_DEFAULT_EXCHANGE,
        type=settings.CELERY_DEFAULT_EXCHANGE_TYPE)
    return Queue(name, exchange=exchange).bind(connection)


def get_queue_size(queue):
    return queue.queue_declare(passive=True).message_count
