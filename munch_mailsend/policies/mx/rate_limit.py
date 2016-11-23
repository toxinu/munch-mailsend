import re
import random
from datetime import datetime
from datetime import timedelta

import pytz
from django_redis import get_redis_connection

from . import CACHE_PREFIX
from . import WorkerPolicyBase

# from celery.contrib import rdb

conn = get_redis_connection('default')


class Policy(WorkerPolicyBase):
    """
        Compute next_available based on latest sending status

        # Example of settings
        priotitize options: `earlier`, `equal`
        {
            'domains': [
                (re.compile(r'.*oasiswork.fr'), 60 * 1),
                (re.compile(r'.*'), 60 * 5)],
            'max_queued': 60 * 30,
            'prioritize': 'earlier'
        }
    """
    def apply(self, workers):
        domain = self.get_domain(self.headers.get('To'))

        now = self.now()
        old = self.old()
        # Taking not_before or we are assuming it's now if not specified
        not_before = self.not_before or now
        for worker in workers:
            prioritize = self.get_settings(worker).get('prioritize', 'earlier')

            domain_limit = 0
            for domain_settings in self.get_settings(
                    worker).get('domains', []):
                if re.match(domain_settings[0], domain):
                    domain_limit = domain_settings[1]
                    self.logger.debug(
                        '[{}] [worker:{}] Domain rate limiting detected at {} '
                        'second(s) for {} (domain:{})'.format(
                            self.identifier, worker.get('ip'),
                            domain_limit, domain, domain_settings[0]))
                    break

            statuses = sorted(self.get_statuses(
                source_ip=worker.get('ip'),
                destination_domain=domain,
                creation_date=now - timedelta(seconds=domain_limit)),
                key=lambda ms: ms.get('creation_date'), reverse=False)
            next_available = None
            # If there is no statuses, we can set next_available at now
            if not statuses:
                next_available = not_before
                self.logger.debug(
                    '[{}] [worker:{}] No previous sending statuses, then '
                    'next_available is now or not_before ({}).'.format(
                        self.identifier, worker.get('ip'),
                        next_available.astimezone()))

            # First check if we can insert before the first scheduled mail
            if statuses:
                status_date = statuses[0].get('creation_date') or old
                if now + timedelta(seconds=domain_limit * 2) < status_date:
                    next_available = now + timedelta(seconds=domain_limit)
                # If next_available is before the not_before constraint
                # Unset next_available and let's continue searching
                if next_available and next_available < not_before:
                    self.logger.debug(
                        '[{}] [worker:{}] Envelope has a not_before ({}) '
                        'and next_available ({}) is too early, '
                        'searching another one...'.format(
                            self.identifier, worker.get('ip'),
                            not_before.astimezone(),
                            next_available.astimezone()))
                    next_available = None

            if not next_available:
                # Keep searching for a next_available after the first
                # scheduled mail
                for i, status in enumerate(statuses):
                    next_status = None
                    status_date = status.get('creation_date') or old
                    # Check if there is another sending status after this one
                    if len(statuses) > i + 1:
                        next_status = statuses[i + 1].get('creation_date')
                    # If it's the only one status or we can schedule
                    # a sending between this and next one
                    if not next_status or status_date + timedelta(
                            seconds=domain_limit * 2) < next_status:
                        # Then compute next available
                        next_available = status_date + timedelta(
                            seconds=domain_limit)
                        # If next_available is before the not_before constraint
                        # Unset next_available and let's continue searching
                        if next_available < not_before:
                            self.logger.debug(
                                '[{}] [worker:{}] Envelope has a not_before '
                                '({}) and next_available ({}) is too early, '
                                'searching another one...'.format(
                                    self.identifier, worker.get('ip'),
                                    not_before.astimezone(),
                                    next_available.astimezone()))
                            next_available = None
                        # Else, break for loop with computed next_available
                        else:
                            self.logger.debug(
                                '[{}] [worker:{}] Potential '
                                'next_available found at {}'.format(
                                    self.identifier,
                                    worker.get('ip'),
                                    next_available.astimezone()))
                            break

            # If we don't find any next_available
            # (because of no statuses for example) or next_available is in past
            # Then we set next_available at not_before which
            # is now if not set.
            if not next_available or next_available < now:
                next_available = not_before
            # If next_available is after the value choosen by a previous policy
            # We override it.
            if next_available > worker.get('next_available', now):
                worker['next_available'] = next_available
            self.logger.debug(
                '[{}] [worker:{}] Final next_available found at {}.'.format(
                    self.identifier, worker.get('ip'),
                    worker.get('next_available').astimezone()))

        # Then order available workers based on next_available
        def get_next_available(worker):
            if worker.get('next_available'):
                return (worker.get('next_available'), random.random())
            return datetime(year=1970, month=1, day=1).replace(
                tzinfo=pytz.utc), random.random()

        workers = sorted(workers, key=get_next_available)
        ranked_workers = []
        for index, worker in enumerate(workers):
            # Discard max_queued
            max_queued = int(self.get_settings(worker).get('max_queued', 30))
            max_queued_datetime = now + timedelta(seconds=max_queued)
            if worker.get('next_available') > max_queued_datetime:
                self.logger.debug(
                    '[{}] [worker:{}] Next available is '
                    'too far (max_queue:{}) to be scheduled '
                    'for this worker (next_available:{})'.format(
                        self.identifier, worker.get('ip'),
                        max_queued_datetime,
                        worker.get('next_available').astimezone()))
                continue
            if prioritize == 'earlier':
                worker['score'] += round((len(workers) - index) * 0.1, 2)
            ranked_workers.append(worker)
        return ranked_workers

    @staticmethod
    def get_statuses(source_ip, destination_domain, creation_date):
        statuses = []
        for status in conn.zrangebyscore(
                '{}:rate_limit:{}:{}'.format(
                    CACHE_PREFIX, source_ip, destination_domain),
                creation_date.timestamp(), '+inf'):
            splitted_status = status.decode('utf-8').split(':')
            statuses.append({
                'identifier': splitted_status[0],
                'creation_date': datetime.fromtimestamp(float(
                    splitted_status[1]), pytz.utc)})
        return statuses

    ###########
    # Signals #
    ###########

    @staticmethod
    def mailstatus_pre_save(instance, manager):
        if instance.status in [instance.SENDING]:
            conn.zadd(
                '{}:rate_limit:{}:{}'.format(
                    CACHE_PREFIX, instance.source_ip,
                    instance.destination_domain),
                instance.creation_date.timestamp(),
                '{}:{}'.format(
                    instance.mail.identifier,
                    instance.creation_date.timestamp()))
