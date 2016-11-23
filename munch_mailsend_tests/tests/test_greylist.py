import copy

from libfaketime import fake_time
from slimta.smtp.reply import Reply
from django.conf import settings
from django.test import override_settings

from munch_mailsend.models import Mail
from munch_mailsend.models import MailStatus
from munch_mailsend import policies
from munch_mailsend.models import Worker
from munch_mailsend.policies.mx import greylist

from . import MailSendTestCase


class GreyListPolicyTestCase(MailSendTestCase):
    def test_greylisting_kk(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={'greylist': {}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={'greylist': {}})

        mail_01 = Mail.objects.create(
            identifier='0001',
            headers={
                'To': 'you@example.com',
                'X-MAILSEND-Message-Id': '0001'})
        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_01, source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_01, status=MailStatus.SENDING,
                source_ip=worker_01.ip)
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_01, status=MailStatus.DELAYED,
                source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:05:00'):
            MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
            MAILSEND_SETTINGS['WORKER_POLICIES'] = [
                'munch_mailsend.policies.mx.greylist.Policy']
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                best_worker, next_available, score, *_ = Worker.objects.\
                    find_worker(
                        mail_01.identifier, mail_01.headers, MailStatus,
                        reply=Reply(code='420', message='4.2.0 GreyListedd'))
            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)
            self.assertEqual(score, 1.0)

    def test_greylisting_not_delayed(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={'greylist': {}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={'greylist': {}})

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
                destination_domain='example.com', mail=mail_metadata_01,
                status=MailStatus.DELIVERED, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:05:00'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = greylist.Policy(
                mail_metadata_01.identifier, {'To': 'test+01@example.com'},
                MailStatus, reply_code='4.2.0',
                reply_message='GreylisTeDd').apply(workers)

            self.assertEqual(worker_ranking[0]['score'], 0.0)
            self.assertEqual(worker_ranking[1]['score'], 0.0)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
