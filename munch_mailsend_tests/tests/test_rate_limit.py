from datetime import datetime
from datetime import timedelta

import pytz
from libfaketime import fake_time

from munch_mailsend.models import Mail
from munch_mailsend.models import Worker
from munch_mailsend.models import MailStatus
from munch_mailsend.policies.mx import rate_limit
from munch_mailsend import policies

from . import MailSendTestCase


class RateLimitPolicyTestCase(MailSendTestCase):
    def setUp(self):
        super().setUp()
        self.default_settings = {
            'rate_limit': {
                'domains': [(r'.*', 60)],
                'max_queued': 60 * 15}}

    def test_one_never_send_mail(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings=self.default_settings)
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings=self.default_settings)

        headers_01 = {'To': 'test+01@example.com'}
        mail_metadata_01 = Mail.objects.create(identifier='0001')

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01,
                status=MailStatus.SENDING,
                source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01,
                status=MailStatus.DELIVERED,
                source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:30'):
            workers = policies.mx.First().apply(headers_01)
            worker_ranking = rate_limit.Policy(
                mail_metadata_01.identifier,
                headers_01, MailStatus).apply(workers)

        self.assertEqual(worker_ranking[0]['score'], 0.2)
        self.assertEqual(worker_ranking[0]['ip'], worker_02.ip)
        self.assertEqual(worker_ranking[1]['score'], 0.1)
        self.assertEqual(worker_ranking[1]['ip'], worker_01.ip)

        best_worker, next_available, *_ = policies.mx.Last().apply(
            worker_ranking)
        self.assertEqual(best_worker.name, worker_02.name)
        self.assertEqual(best_worker.ip, worker_02.ip)

    def test_simple_ordering(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings=self.default_settings)
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings=self.default_settings)

        headers_01 = {'To': 'test+01@example.com'}
        headers_02 = {'To': 'test+02@example.com'}
        headers_03 = {'To': 'test+03@example.com'}
        headers_04 = {'To': 'test+04@example.com'}
        mail_metadata_01 = Mail.objects.create(identifier='0001')
        mail_metadata_02 = Mail.objects.create(identifier='0002')
        mail_metadata_03 = Mail.objects.create(identifier='0003')
        mail_metadata_04 = Mail.objects.create(identifier='0004')

        # Worker 02 send first mail to test+03@example2.com
        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_02.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01,
                status=MailStatus.DELIVERED,
                source_ip=worker_02.ip)
        # Worker 01 send mail to test+01@example.com
        with fake_time('2015-12-10 12:00:10'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_02, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_02,
                status=MailStatus.DELIVERED,
                source_ip=worker_01.ip)
        # Worker 02 send mail to test+02@example.com
        with fake_time('2015-12-10 12:00:20'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_03, source_ip=worker_02.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                status=MailStatus.SENDING,
                mail=mail_metadata_03, source_ip=worker_02.ip)

        with fake_time('2015-12-10 12:00:15'):
            # Test for test+01@example.com
            workers = policies.mx.First().apply(headers_01)
            worker_ranking = rate_limit.Policy(
                mail_metadata_04.identifier,
                headers_04, MailStatus).apply(workers)

            self.assertEqual(worker_ranking[0]['score'], 0.2)
            self.assertEqual(worker_ranking[0]['ip'], worker_01.ip)
            self.assertEqual(worker_ranking[1]['score'], 0.1)
            self.assertEqual(worker_ranking[1]['ip'], worker_02.ip)

            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)

            # Test for test+02@example.com
            # Must be the same as test+02@example.com
            workers = policies.mx.First().apply(headers_02)
            worker_ranking = rate_limit.Policy(
                mail_metadata_02.identifier,
                headers_02, MailStatus).apply(workers)

            self.assertEqual(worker_ranking[0]['score'], 0.2)
            self.assertEqual(worker_ranking[0]['ip'], worker_01.ip)
            self.assertEqual(worker_ranking[1]['score'], 0.1)
            self.assertEqual(worker_ranking[1]['ip'], worker_02.ip)

            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)

            # Test for test+03@example2.com
            workers = policies.mx.First().apply(headers_03)
            worker_ranking = rate_limit.Policy(
                mail_metadata_03.identifier, headers_03, MailStatus).apply(
                    workers)

            self.assertEqual(worker_ranking[0]['score'], 0.2)
            self.assertEqual(worker_ranking[0]['ip'], worker_01.ip)
            self.assertEqual(worker_ranking[1]['score'], 0.1)
            self.assertEqual(worker_ranking[1]['ip'], worker_02.ip)

            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)

    def test_interval_between_sending(self):
        worker = Worker.objects.create(
            name='worker', ip='10.0.0.1',
            policies_settings=self.default_settings)

        with fake_time('2015-12-10 12:00:00'):
            mail_01 = Mail.objects.create(identifier='0001')
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_01, source_ip=worker.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_01, status=MailStatus.SENDING, source_ip=worker.ip)

        with fake_time('2015-12-10 12:05:00'):
            mail_02 = Mail.objects.create(identifier='0002')
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_02, source_ip=worker.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_02, status=MailStatus.SENDING, source_ip=worker.ip)

        with fake_time('2015-12-10 12:01:00'):
            mail_03 = Mail.objects.create(identifier='0003')
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_03, source_ip=worker.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_03, status=MailStatus.SENDING, source_ip=worker.ip)

            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = rate_limit.Policy(
                mail_03.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(next_available, datetime.now(
                pytz.UTC) + timedelta(minutes=1))

    def test_setting_limiting(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings=self.default_settings)
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings=self.default_settings)

        headers_01 = {'To': 'test+01@example.com'}
        mail_metadata_01 = Mail.objects.create(identifier='0001')

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01,
                status=MailStatus.SENDING,
                source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01,
                status=MailStatus.DELIVERED,
                source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:30'):
            workers = policies.mx.First().apply(headers_01)
            worker_ranking = rate_limit.Policy(
                mail_metadata_01.identifier,
                headers_01, MailStatus).apply(workers)

        self.assertEqual(len(worker_ranking), 2)

        self.assertEqual(worker_ranking[0]['score'], 0.2)
        self.assertEqual(worker_ranking[0]['ip'], worker_02.ip)
        self.assertEqual(worker_ranking[0]['name'], worker_02.name)

        best_worker, next_available, *_ = policies.mx.Last().apply(
            worker_ranking)
        self.assertEqual(best_worker.name, worker_02.name)
        self.assertEqual(best_worker.ip, worker_02.ip)

    def test_setting_domain_catched(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1', policies_settings={
                'rate_limit': {
                    'domains': [
                        (r'example.com', 60 * 5),
                        (r'.*', 60)],
                    'max_queued': 60 * 15}})

        headers_01 = {'To': 'test+01@example.com'}
        headers_02 = {'To': 'test+02@example.com'}
        mail_01 = Mail.objects.create(identifier='0001')
        mail_02 = Mail.objects.create(identifier='0002')

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_01, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com', mail=mail_01,
                status=MailStatus.SENDING, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com', mail=mail_01,
                status=MailStatus.DELIVERED, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:00'):
            workers = policies.mx.First().apply(headers_01)
            worker_ranking = rate_limit.Policy(
                mail_01.identifier, headers_01, MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker, worker_01)
            self.assertEqual(next_available, datetime.now(
                pytz.UTC) + timedelta(minutes=5))

        with fake_time('2015-12-10 12:05:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_02, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com', mail=mail_02,
                status=MailStatus.DELIVERED, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:05:30'):
            workers = policies.mx.First().apply(headers_02)
            worker_ranking = rate_limit.Policy(
                mail_02.identifier, headers_02, MailStatus).apply(workers)

        self.assertEqual(len(worker_ranking), 1)
        self.assertEqual(worker_ranking[0]['score'], 0.1)
        self.assertEqual(worker_ranking[0]['ip'], worker_01.ip)
        self.assertEqual(worker_ranking[0]['name'], worker_01.name)

        best_worker, next_available, *_ = policies.mx.Last().apply(
            worker_ranking)
        self.assertEqual(best_worker.name, worker_01.name)
        self.assertEqual(best_worker.ip, worker_01.ip)
