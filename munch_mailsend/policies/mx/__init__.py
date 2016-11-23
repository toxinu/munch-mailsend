import logging
from datetime import datetime

import pytz
from django.conf import settings
from django.utils import timezone

from munch.core.mail.utils import extract_domain

from ...models import Worker

CACHE_PREFIX = '{}:{}'.format(
    settings.MAILSEND['CACHE_PREFIX'],
    settings.MAILSEND['MAILSTATUS_CACHE_PREFIX'])
CACHE_TIMEOUT = settings.MAILSEND['MAILSTATUS_CACHE_TIMEOUT']


class First:
    def apply(self, headers, not_before=None):
        workers = list(Worker.objects.get_from_cache())
        if not workers:
            for worker in Worker.objects.filter(enabled=True):
                Worker.objects.set_to_cache(worker)
            workers = list(Worker.objects.get_from_cache())
        for worker in workers:
            worker['score'] = 0.0
            worker['next_available'] = not_before or timezone.now()
        return workers


class Last:
    def apply(self, workers):
        if workers:
            worker = max(workers, key=lambda worker: worker['score'])
            return (
                Worker.objects.get(ip=worker.get('ip')),
                worker.get('next_available'),
                worker.get('score'),
                workers)
        return (None, None, None, {})


class WorkerPolicyException(Exception):
    pass


class WorkerPolicyBase:
    def __init__(
            self, identifier, headers, mail_status_class, reply_code=None,
            reply_message=None, not_before=None):
        self.headers = headers
        self.identifier = identifier
        self.not_before = not_before
        self.reply_code = reply_code
        self.reply_message = reply_message
        self.mail_statuses = mail_status_class
        self.logger = logging.getLogger(__name__)

    def get_settings(self, worker):
        return worker.get('policies_settings', {}).get(
            self.__module__.split('.')[-1], {})

    def old(self):
        return datetime(year=1970, month=1, day=1).replace(tzinfo=pytz.utc)

    def now(self):
        return datetime.utcnow().replace(tzinfo=pytz.utc)

    def get_domain(self, address):
        return extract_domain(address)

    def apply(self, workers):
        """
            This method must only return workers with updated:
                `next_available` and `score`
        """
        raise NotImplementedError

    ###########
    # Signals #
    ###########
    @classmethod
    def mailstatus_pre_save(cls, instance, manager):
        pass

    @classmethod
    def mailstatus_post_save(cls, instance, manager):
        pass
