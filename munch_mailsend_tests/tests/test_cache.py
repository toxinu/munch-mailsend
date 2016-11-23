import copy

from django.conf import settings
from django.utils import timezone
from django.test import override_settings
from libfaketime import fake_time
from django_redis import get_redis_connection

from munch_mailsend.models import Mail
from munch_mailsend.models import Worker
from munch_mailsend.policies.mx.warm_up import Policy as WarmUpPolicy
from munch_mailsend.policies.mx.rate_limit import Policy as RateLimitPolicy

from . import MailSendTestCase
from ..models import MailStatus

conn = get_redis_connection('default')


class MailStatusCacheTestCase(MailSendTestCase):
    def setUp(self):
        super().setUp()
        self.settings = {
            'warm_up': {
                'prioritize': 'equal',
                'domain_warm_up': {
                    'matrix': [5, 10, 30, 50, 100],
                    'goal': 50, 'step_tolerance': 10, 'max_tolerance': 10},
                'ip_warm_up': {
                    'enabled': True,
                    'matrix': [5, 10, 30, 50, 100],
                    'goal': 50, 'step_tolerance': 10, 'max_tolerance': 10}
            }
        }

    def create_mails(
            self, worker, number, destination_domain=None, warm_up_domains={}):
        now = timezone.now()
        MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
        if warm_up_domains:
            MAILSEND_SETTINGS['WARM_UP_DOMAINS'] = warm_up_domains
        with override_settings(MAILSEND=MAILSEND_SETTINGS):
            for i in range(0, number):
                identifier = "{}.{}.{}".format(worker.name, i, now.timestamp())
                mail = Mail.objects.create(
                    headers={
                        'To': 'you@{}'.format(
                            destination_domain or 'example.com'),
                        'X-MAILSEND-Message-Id': identifier},
                    identifier=identifier,
                    recipient='you@{}'.format(destination_domain))
                MailStatus.objects.create(
                    destination_domain=destination_domain or 'example.com',
                    mail=mail, source_ip=worker.ip,
                    status=MailStatus.QUEUED)

                best_worker, next_available, score, *_ = Worker.objects.\
                    find_worker(identifier, mail.headers, MailStatus)

                MailStatus.objects.create(
                    destination_domain=destination_domain or 'example.com',
                    mail=mail,
                    status=MailStatus.SENDING,
                    source_ip=worker.ip)

                MailStatus.objects.create(
                    destination_domain=destination_domain or 'example.com',
                    mail=mail,
                    status=MailStatus.DELIVERED,
                    source_ip=worker.ip)

    def test_build_cache(self):
        worker = Worker.objects.create(
            name='worker_01', ip='10.0.0.1', policies_settings=self.settings)
        warm_up_domains = {'foo': ['bar.com', 'foo.com']}
        MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
        MAILSEND_SETTINGS['WARM_UP_DOMAINS'] = warm_up_domains

        with fake_time('2015-12-10 12:00:00'):
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                now = timezone.now()
                self.create_mails(
                    worker, 5,
                    destination_domain='bar.com',
                    warm_up_domains=warm_up_domains)
                self.assertEqual(
                    len(RateLimitPolicy.get_statuses(
                        worker.ip, 'bar.com', now)), 5)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (5, 0))
                for key in conn.scan_iter('{}:{}:*'.format(
                        settings.MAILSEND['CACHE_PREFIX'],
                        settings.MAILSEND['MAILSTATUS_CACHE_PREFIX'])):
                    conn.delete(key)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (None, None))
                MailStatus.objects.re_run_signals(
                    settings.MAILSEND['MAILSTATUS_CACHE_TIMEOUT'])
                self.assertEqual(
                    len(RateLimitPolicy.get_statuses(
                        worker.ip, 'bar.com', now)), 5)
                # Remains start at 0 because this is WarmUpPolicy which set it
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (None, -5))

        with fake_time('2015-12-10 12:00:05'):
            warm_up_domains = {'foo': ['bar.com', 'foo.com']}
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                self.create_mails(
                    worker, 1, destination_domain='bar.com',
                    warm_up_domains=warm_up_domains)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (5, -1))

        with fake_time('2015-12-11 12:00:00'):
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                self.create_mails(
                    worker, 1, destination_domain='bar.com',
                    warm_up_domains=warm_up_domains)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (10, 10))

        with fake_time('2015-12-11 12:00:05'):
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                self.create_mails(
                    worker, 11, destination_domain='bar.com',
                    warm_up_domains=warm_up_domains)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (10, -1))
                for key in conn.scan_iter('{}:{}:*'.format(
                        settings.MAILSEND['CACHE_PREFIX'],
                        settings.MAILSEND['MAILSTATUS_CACHE_PREFIX'])):
                    conn.delete(key)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (None, None))
                MailStatus.objects.re_run_signals(
                    settings.MAILSEND['MAILSTATUS_CACHE_TIMEOUT'])
                # Remains start at 0 because this is WarmUpPolicy which set it
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (None, -12))

        with fake_time('2015-12-12 12:00:00'):
            warm_up_domains = {'foo': ['bar.com', 'foo.com']}
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                self.create_mails(
                    worker, 1, destination_domain='bar.com',
                    warm_up_domains=warm_up_domains)
                self.assertEqual(
                    WarmUpPolicy.get_step(worker.ip, 'foo'), (30, 32))
