import sys

from celery.signals import worker_shutdown
from celery.signals import celeryd_after_setup
from django.conf import settings

from munch.core.utils import get_worker_types
from munch.core.utils import available_worker_types
from munch.core.celery import catch_exception
from munch.core.celery import munch_tasks_router

available_worker_types += ['mx', 'router']


def add_queues():
    munch_tasks_router.add_queue(
        'router', settings.MAILSEND.get('ROUTING_QUEUE'))
    munch_tasks_router.add_queue(
        'holder', settings.MAILSEND.get('QUEUED_MAIL_QUEUE'))


def register_tasks():
    tasks_map = {
        'router': ['munch_mailsend.tasks.route_envelope'],
        'gc': [
            'munch_mailsend.tasks.ping_workers',
            'munch_mailsend.tasks.check_disabled_workers',
            'munch_mailsend.tasks.dispatch_queued',
            'munch_mailsend.tasks.purge_raw_mail'
        ]
    }
    munch_tasks_router.import_tasks_map(tasks_map, 'munch_mailsend')


@celeryd_after_setup.connect
@catch_exception
def configure_worker(instance, **kwargs):
    from .models import Worker

    if any([t in get_worker_types() for t in ['mx', 'all']]):
        from .tasks import send_email  # noqa
        sys.stdout.write('[mailsend-app] Registering worker as MX...')
        if not settings.MAILSEND.get('SMTP_WORKER_EHLO_AS') or \
                not settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'):
            raise Exception(
                'Settings must define "SMTP_WORKER_EHLO_AS" '
                'and "SMTP_WORKER_SRC_ADDR"')
        worker, created = Worker.objects.get_or_create(
            ip=settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'))
        worker.name = kwargs.get('sender')
        worker.policies_settings = settings.MAILSEND.get(
            'WORKER_POLICIES_SETTINGS', {})
        worker.enabled = True
        worker.save()
        queue = settings.MAILSEND.get(
            'MX_WORKER_QUEUE_PREFIX', '').format(ip=worker.ip)
        munch_tasks_router.register_to_queue(queue)
        queue = settings.MAILSEND.get(
            'MX_WORKER_QUEUE_RETRY_PREFIX', '').format(ip=worker.ip)
        munch_tasks_router.register_to_queue(queue)
    if any([t in get_worker_types() for t in ['router', 'all']]):
        from .tasks import route_envelope  # noqa
        sys.stdout.write('[mailsend-app] Registering worker as ROUTER...')
        munch_tasks_router.register_as_worker('router')
    if any([t in get_worker_types() for t in ['gc', 'all']]):
        from .tasks import ping_workers  # noqa
        from .tasks import dispatch_queued  # noqa
        from .tasks import check_disabled_workers  # noqa
        sys.stdout.write(
            '[mailsend-app] Registering worker as GARBAGE COLLECTOR...')
        munch_tasks_router.register_as_worker('gc')


@worker_shutdown.connect
def worker_shutdown(*args, **kwargs):
    from .models import Worker
    sender = kwargs.get('sender')

    if any([t in get_worker_types() for t in ['mx', 'all']]):
        sys.stdout.write('[mailsend-app] Disabling MX worker instance...')
        workers = Worker.objects.filter(
            ip=settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'), name=sender)
        if not workers:
            raise Exception(
                "Want to disable worker ({} / {}) but can't find it. "
                "Abnormal situation.".format(
                    settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'), sender))
        if len(workers) > 1:
            raise Exception(
                "Want to disable worker ({} / {}) but found multiple. "
                "Abnormal situation.".format(
                    settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'), sender))

        workers[0].enabled = False
        workers[0].save()
        sys.stdout.write(
            '[mailsend-app] MX worker disabled and removed from cache. Bye !')
