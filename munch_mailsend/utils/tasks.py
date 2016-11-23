import logging
from time import sleep

from django.core.exceptions import ObjectDoesNotExist
from django_redis import get_redis_connection

log = logging.getLogger(__name__)

conn = get_redis_connection('default')


def acquire_lock(
        lock_name, blocking_timeout=5, timeout=60 * 5, interval=0.1):
    lock = None
    counter = 0
    while not lock and counter < blocking_timeout:
        lock = conn.set(lock_name, 'true', timeout)
        counter += interval
        sleep(interval)
    return lock


def release_lock(lock_name):
    return conn.delete(lock_name)


def record_status(mailstatus, identifier, ehlo=None, reply=None):
    from ..models import Mail

    try:
        mailstatus.mail
    except ObjectDoesNotExist:
        mailstatus.mail = Mail.objects.get(identifier=identifier)
        mailstatus.save()


def get_envelope(identifier):
    from ..models import Mail

    return Mail.objects.get(identifier=identifier).as_envelope()
