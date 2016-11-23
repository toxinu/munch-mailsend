import random
from datetime import date
from datetime import timedelta

from django.conf import settings
from django_redis import get_redis_connection

from . import CACHE_PREFIX
from . import CACHE_TIMEOUT
from . import WorkerPolicyBase

conn = get_redis_connection('default')


class Policy(WorkerPolicyBase):
    """
        Warm up

        Prioritize: "equal", "warmest", "coldest"

        {
            'prioritize': 'equal',
            'domain_warm_up': {
                'matrix': [50, 100, 300, 500, 1000],
                'goal': 500,
                'max_tolerance': 10,
                'step_tolerance': 10,
                'days_watched': 10,
            },
            'ip_warm_up': {
                'matrix': [50, 100, 300, 500, 1000],
                'goal': 500,
                'max_tolerance': 10,
                'step_tolerance': 10,
                'enabled': False,
                'days_watched': 10,
            }
        }
    """
    def get_specific_settings(self, domain, policy_settings):
        if self.get_domain_group(domain):
            return policy_settings.get('domain_warm_up', {})
        elif policy_settings.get('ip_warm_up', {}).get('enabled'):
            return policy_settings.get('ip_warm_up', {})
        return {}

    def apply(self, workers):
        today = date.today()
        domain = self.get_domain(self.headers.get('To'))
        mailstatus_cache_timeout = int(settings.MAILSEND[
            'MAILSTATUS_CACHE_TIMEOUT'] / (60 * 60 * 24))

        for worker in workers:
            policy_settings = self.get_specific_settings(
                domain, self.get_settings(worker))

            domain_group = self.get_domain_group(domain)
            mail_statuses_kwargs = {'source_ip': worker.get('ip')}
            if domain_group:
                self.logger.debug(
                    '[{}] [worker:{}] This envelope will have a '
                    'warm-up just for its domain group ({})'.format(
                        self.identifier, worker.get('ip'), domain_group))
                mail_statuses_kwargs.update(
                    {'destination_domain': self.get_shared_domains(
                        domain_group)})
            elif policy_settings.get('enabled', False):
                self.logger.debug(
                    '[{}] [worker:{}] Applying ip warm-up...'.format(
                        self.identifier, worker.get('ip')))
            else:
                self.logger.debug(
                    '[{}] [worker:{}] This envelope will not have any '
                    'warm-up share with these domains ({}). '
                    'Missing percent set at 100%.'.format(
                        self.identifier, worker.get('ip'), domain))
                worker['_warm_up_step'] = 0
                worker['_warm_up_missing_percent'] = 100
                continue

            days_watched = int(policy_settings.get(
                'days_watched', mailstatus_cache_timeout))

            if days_watched > mailstatus_cache_timeout:
                self.logger.warning(
                    '[{}] [worker:{}] "days_watched" is higher than '
                    '"MAILSEND[\'MAILSTATUS_CACHE_TIMEOUT\']". Fallback to '
                    'this value.'.format(self.identifier, worker.get('ip')))
                days_watched = mailstatus_cache_timeout

            # Retrieve step from cache
            step, remains = self.get_step(
                worker.get('ip'), domain_group=domain_group)
            # If step return is None, lets search and cache it
            if step is None:
                self.logger.debug(
                    '[{}] [worker:{}] Building cache for step '
                    'and remains...'.format(self.identifier, worker.get('ip')))
                step_tolerance = int(policy_settings.get('step_tolerance'))
                goal = int(policy_settings.get('goal'))
                matrix = policy_settings.get('matrix', [])
                step = self.search_step(
                    worker=worker, days_watched=days_watched, goal=goal,
                    step_tolerance=step_tolerance, matrix=matrix, today=today,
                    mail_statuses_kwargs=mail_statuses_kwargs)
                remains = step + int(policy_settings.get(
                    'max_tolerance', 0) * step / 100)
                self.set_step(
                    worker.get('ip'), step, remains, domain_group=domain_group)

            missing_percent = 100 - int((step - remains) * 100 / step)
            self.logger.debug(
                '[{}] [worker:{}] Remains for today is {} for {} '
                'step (missing_percent:{})'.format(
                    self.identifier, worker.get('ip'),
                    remains, step, missing_percent))
            worker['_warm_up_step'] = step
            worker['_warm_up_missing_percent'] = missing_percent

        return self.apply_prioritize(workers, domain)

    def apply_prioritize(self, workers, domain):
        prioritize = settings.MAILSEND.get(
            'WORKER_POLICIES_SETTINGS', {}).get('warm_up', {}).get(
                'prioritize', 'equal').lower()

        if prioritize == 'warmest':
            workers = sorted(
                workers, key=lambda k: (k['_warm_up_step'], random.random()))
        elif prioritize == 'coldest':
            workers = sorted(
                workers, reverse=True,
                key=lambda k: (k['_warm_up_step'], random.random()))

        ranked_workers = []
        for i, worker in enumerate(workers):
            if worker.get('_warm_up_missing_percent') <= 0:
                self.logger.debug(
                    "[{}] [worker:{}] Can't keep this worker because it reach"
                    " its step + max_tolerance: {}".format(
                        self.identifier, worker.get('ip'), 100 - worker.get(
                            '_warm_up_missing_percent')))
                continue
            percent = worker.get('_warm_up_missing_percent')
            if prioritize == 'equal':
                worker['score'] += round(percent * 0.01 / len(workers), 2)
            elif prioritize == 'warmest':
                worker['score'] += round(
                    percent * 0.01 / len(workers), 2) + 0.1 * i
            elif prioritize == 'coldest':
                worker['score'] += round(
                    percent * 0.01 / len(workers), 2) + 0.1 * i
            ranked_workers.append(worker)

        ranked_workers = sorted(ranked_workers, key=lambda k: k['score'])
        for worker in ranked_workers:
            worker.pop('_warm_up_step')
            worker.pop('_warm_up_missing_percent')
        return ranked_workers

    def search_step(
            self, worker, days_watched, matrix, goal,
            step_tolerance, today, mail_statuses_kwargs):
        step = 0

        for days in range(days_watched):
            days += 1

            day_to_watch = today - timedelta(days=days)
            mail_statuses_kwargs.update({'creation_date': day_to_watch})
            latest_counter = self.get_counter(**mail_statuses_kwargs)

            if not latest_counter:
                if matrix[0] > step:
                    step = matrix[0]
                    self.logger.debug(
                        '[{}] [worker:{}] Not statuses for today - {} '
                        'day(s). Start matrix at first '
                        'step, which is {}.'.format(
                            self.identifier, worker.get('ip'), days, step))
            else:
                self.logger.debug(
                    '[{}] [worker:{}] Today - {} day(s) '
                    'statuses count: {}.'.format(
                        self.identifier, worker.get('ip'),
                        days, latest_counter))
                for i, _step in enumerate(matrix):
                    if len(matrix) > i + 1:
                        next_step = matrix[i + 1]
                    else:
                        next_step = matrix[i]

                    up_counter = int(
                        next_step - next_step * step_tolerance / 100)
                    down_counter = int(
                        step - step * step_tolerance / 100)
                    if down_counter <= latest_counter < up_counter:
                        if int(matrix[i + 1]) > step:
                            self.logger.debug(
                                '[{}] [worker:{}] Found a new higher'
                                ' step at {} from {}.'.format(
                                    self.identifier, worker.get('ip'),
                                    int(matrix[i + 1]), step))
                            step = int(matrix[i + 1])
                            break

            if step > goal:
                self.logger.debug(
                    '[{}] [worker:{}] Step is greater than goal. Set step '
                    'to goal ({} => {})'.format(
                        self.identifier, worker.get('ip'), step, goal))
                step = goal

            return step

    @staticmethod
    def get_domain_group(domain):
        for domain_group, domains in settings.MAILSEND.get(
                'WARM_UP_DOMAINS', {}).items():
            if domain in domains:
                return domain_group

    @staticmethod
    def get_shared_domains(domain_group):
        return settings.MAILSEND.get(
            'WARM_UP_DOMAINS', {}).get(domain_group, [])

    @classmethod
    def update_counter(
            cls, source_ip, destination_domain, value, creation_date=None):
        if creation_date:
            creation_date = creation_date.strftime('%Y-%m-%d')
        else:
            creation_date = date.today().strftime('%Y-%m-%d')
        domain_group = cls.get_domain_group(destination_domain)
        key_base = '{}:warm_up:remains:{}:{}'.format(
            CACHE_PREFIX, creation_date, source_ip)
        if value == 1:
            if conn.get(key_base) is None:
                conn.set(key_base, 1, CACHE_TIMEOUT)
            else:
                conn.incr(key_base)
            if domain_group:
                key_base = '{}:{}'.format(key_base, domain_group)
                if conn.get(key_base) is None:
                    conn.set(key_base, 1, CACHE_TIMEOUT)
                else:
                    conn.incr(key_base)
        elif value == -1:
            if conn.get(key_base) is None:
                conn.set(key_base, -1, CACHE_TIMEOUT)
            else:
                conn.decr(key_base)
            if domain_group:
                key_base = '{}:{}'.format(key_base, domain_group)
                if conn.get(key_base) is None:
                    conn.set(key_base, -1, CACHE_TIMEOUT)
                else:
                    conn.decr(key_base)

    @staticmethod
    def set_step(
            source_ip, step, remains, domain_group=None):
        creation_date = date.today().strftime('%Y-%m-%d')
        ########
        # Step #
        ########
        key_base = '{}:warm_up:step:{}:{}'.format(
            CACHE_PREFIX, creation_date, source_ip)
        if not domain_group:
            conn.set(key_base, step, CACHE_TIMEOUT)
        else:
            conn.set(key_base + ':' + domain_group, step, CACHE_TIMEOUT)
        ###########
        # Remains #
        ###########
        key_base = '{}:warm_up:remains:{}:{}'.format(
            CACHE_PREFIX, creation_date, source_ip)
        if not domain_group:
            if conn.get(key_base) is None:
                conn.set(key_base, remains, CACHE_TIMEOUT)
            else:
                conn.incr(key_base, remains)
        else:
            key_base = key_base + ':' + domain_group
            if conn.get(key_base) is None:
                conn.set(key_base, remains, CACHE_TIMEOUT)
            else:
                conn.incr(key_base, remains)

    @staticmethod
    def get_step(source_ip, domain_group=None):
        step, remains = None, None
        creation_date = date.today().strftime('%Y-%m-%d')
        ########
        # Step #
        ########
        key_base = '{}:warm_up:step:{}:{}'.format(
            CACHE_PREFIX, creation_date, source_ip)
        if not domain_group:
            step = conn.get(key_base)
        else:
            step = conn.get(key_base + ':' + domain_group)
        ###########
        # Remains #
        ###########
        key_base = '{}:warm_up:remains:{}:{}'.format(
            CACHE_PREFIX, creation_date, source_ip)
        if not domain_group:
            remains = conn.get(key_base)
        else:
            remains = conn.get(key_base + ':' + domain_group)

        try:
            step = int(step)
        except (ValueError, TypeError):
            step = None
        try:
            remains = int(remains)
        except (ValueError, TypeError):
            remains = None

        return step, remains

    @staticmethod
    def get_counter(creation_date, source_ip, destination_domain=None):
        key_base = '{}:warm_up:counter:{}:{}'.format(
            CACHE_PREFIX,
            creation_date.strftime('%Y-%m-%d'), source_ip or '*')
        if not destination_domain:
            try:
                return int(conn.get(key_base))
            except (ValueError, TypeError):
                return 0
        if not isinstance(destination_domain, list) and not isinstance(
                destination_domain, tuple):
            destination_domain = (destination_domain, )
        counter = 0
        for domain in destination_domain:
            for key in conn.scan_iter('{}:{}'.format(key_base, domain)):
                try:
                    counter += int(conn.get(key))
                except (ValueError, TypeError):
                    pass
        return counter

    ###########
    # Signals #
    ###########

    @classmethod
    def mailstatus_pre_save(cls, instance, manager):
        if instance.status in [instance.SENDING]:
            cls.update_counter(
                instance.source_ip, instance.destination_domain,
                -1, creation_date=instance.creation_date)
        if instance.status in [instance.DELAYED]:
            cls.update_counter(
                instance.source_ip, instance.destination_domain,
                +1, creation_date=instance.creation_date)
        if instance.status in [instance.DELIVERED, instance.BOUNCED]:
            # Key example which is a counter:
            # ms:warm_up:1990-01-01:127.0.0.1:postfix.example.com
            key = '{}:warm_up:counter:{}:{}:{}'.format(
                CACHE_PREFIX,
                instance.creation_date.strftime('%Y-%m-%d'),
                instance.source_ip, instance.destination_domain)
            key_worker = '{}:warm_up:counter:{}:{}'.format(
                CACHE_PREFIX,
                instance.creation_date.strftime('%Y-%m-%d'),
                instance.source_ip)
            if conn.get(key) is None:
                conn.set(key, 0, CACHE_TIMEOUT)
            if conn.get(key_worker) is None:
                conn.set(key_worker, 0, CACHE_TIMEOUT)
            conn.incr(key)
            conn.incr(key_worker)
