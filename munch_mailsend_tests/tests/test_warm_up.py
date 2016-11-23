import copy

from django.conf import settings
from django.utils import timezone
from django.test import override_settings
from libfaketime import fake_time

from munch_mailsend import policies
from munch_mailsend.models import Mail
from munch_mailsend.models import Worker
from munch_mailsend.models import MailStatus
from munch_mailsend.policies.mx import warm_up

from . import MailSendTestCase


class WarmUpPolicyTestCase(MailSendTestCase):
    def setUp(self):
        super().setUp()
        self.default_settings = {
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
        MAILSEND_SETTINGS['WORKER_POLICIES'] = [
            'munch_mailsend.policies.mx.warm_up.Policy']
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
                    identifier=identifier)
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

    def test_simple_priority(self):
        """ Simple priority between two workers """
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings=self.default_settings)
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings=self.default_settings)

        with fake_time('2015-12-09 12:00:00'):
            self.create_mails(worker_01, 5)
            self.create_mails(worker_02, 5)

        with fake_time('2015-12-10 12:00:00'):
            self.create_mails(worker_01, 10)
            self.create_mails(worker_02, 9)

        with fake_time('2015-12-11 12:00:00'):
            self.create_mails(worker_01, 2)

        with fake_time('2015-12-11 18:30:30'):
            mail_metadata = Mail.objects.create(identifier="test-du-jambon")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)

            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker_02.name)
            self.assertEqual(best_worker.ip, worker_02.ip)

    def test_reached_steps_are_discared(self):
        """ No yesterday stats, then workers must start at first step """
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings=self.default_settings)
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings=self.default_settings)

        with fake_time('2015-12-09 12:00:00'):
            self.create_mails(worker_01, 5)
            self.create_mails(worker_02, 5)

        with fake_time('2015-12-10 12:00:00'):
            self.create_mails(worker_01, 11)
            self.create_mails(worker_02, 11)

        with fake_time('2015-12-10 18:30:30'):
            mail_metadata = Mail.objects.create(identifier="test_one")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 0)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertIsNone(best_worker)

    def test_next_step(self):
        """ Reach each step every day (testing step_tolerance by the way) """
        worker = Worker.objects.create(
            name='worker', ip='10.0.0.1',
            policies_settings=self.default_settings)

        with fake_time('2015-12-10 12:00:00'):
            self.create_mails(worker, 4)

        with fake_time('2015-12-10 12:00:30'):
            mail_metadata = Mail.objects.create(identifier="1")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(best_worker.ip, worker.ip)

        with fake_time('2015-12-11 12:00:00'):
            self.create_mails(worker, 10)

        with fake_time('2015-12-11 12:00:30'):
            mail_metadata = Mail.objects.create(identifier="2")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(best_worker.ip, worker.ip)

        with fake_time('2015-12-12 12:00:00'):
            self.create_mails(worker, 32)
        with fake_time('2015-12-12 12:00:30'):
            mail_metadata = Mail.objects.create(identifier="3")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(best_worker.ip, worker.ip)

        with fake_time('2015-12-13 12:00:00'):
            self.create_mails(worker, 49)
        with fake_time('2015-12-13 12:00:30'):
            mail_metadata = Mail.objects.create(identifier="4")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(best_worker.ip, worker.ip)

        with fake_time('2015-12-14 12:00:00'):
            self.create_mails(worker, 54)
        with fake_time('2015-12-14 12:00:30'):
            mail_metadata = Mail.objects.create(identifier="5")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(best_worker.ip, worker.ip)

        with fake_time('2015-12-14 12:00:35'):
            self.create_mails(worker, 1)
            mail_metadata = Mail.objects.create(identifier="6")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier,
                {'To': 'test@example.com'}, MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertIsNone(best_worker)

    def test_max_step_tolerance(self):
        worker = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={
                'warm_up': {
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 10, 'max_tolerance': 0,
                        'enabled': True}}})

        with fake_time('2015-12-09 12:00:00'):
            self.create_mails(worker, 5)

        with fake_time('2015-12-10 12:00:00'):
            self.create_mails(worker, 10)

        with fake_time('2015-12-11 12:00:00'):
            self.create_mails(worker, 30)

        with fake_time('2015-12-11 18:30:30'):
            mail_metadata = Mail.objects.create(identifier="test_one")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier, {'To': 'test@example.com'},
                MailStatus).apply(workers)

        best_worker, next_available, *_ = policies.mx.Last().apply(
            worker_ranking)
        self.assertIsNone(best_worker)
        self.assertIsNone(next_available)

    def test_prioritize_warmest(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1', policies_settings={
                'warm_up': {
                    'prioritize': 'warmest',
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 10,
                        'max_tolerance': 10, 'enabled': True}}})
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2', policies_settings={
                'warm_up': {
                    'prioritize': 'warmest',
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 10,
                        'max_tolerance': 10, 'enabled': True}}})

        with fake_time('2015-12-10 12:00:00'):
            self.create_mails(worker_01, 5)
            self.create_mails(worker_02, 5)

        with fake_time('2015-12-11 12:00:00'):
            self.create_mails(worker_01, 5)
            self.create_mails(worker_02, 3)

        with fake_time('2015-12-11 12:05:00'):
            MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
            MAILSEND_SETTINGS['WORKER_POLICIES_SETTINGS'][
                'warm_up']['prioritize'] = 'warmest'
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                mail = Mail.objects.create(
                    identifier="1",
                    headers={
                        'To': 'test@example.com',
                        'X-MAILSEND-Message-Id': '1'})
                workers = policies.mx.First().apply(mail.headers)
                worker_ranking = warm_up.Policy(
                    mail.identifier, mail.headers,
                    MailStatus).apply(workers)
                best_worker, next_available, *_ = policies.mx.Last().apply(
                    worker_ranking)
                self.assertEqual(best_worker.name, worker_02.name)
                self.assertEqual(best_worker.ip, worker_02.ip)

    def test_prioritize_coldest(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1', policies_settings={
                'warm_up': {
                    'prioritize': 'coldest',
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 10,
                        'max_tolerance': 10, 'enabled': True}}})
        worker_02 = Worker.objects.create(
            name='worker_02', ip='10.0.0.2', policies_settings={
                'warm_up': {
                    'prioritize': 'coldest',
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 10,
                        'max_tolerance': 10, 'enabled': True}}})

        with fake_time('2015-12-10 12:00:00'):
            self.create_mails(worker_01, 5)
            self.create_mails(worker_02, 5)

        with fake_time('2015-12-11 12:00:00'):
            self.create_mails(worker_01, 1)
            self.create_mails(worker_02, 8)

        with fake_time('2015-12-11 12:05:00'):
            MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
            MAILSEND_SETTINGS['WORKER_POLICIES_SETTINGS'][
                'warm_up']['prioritize'] = 'coldest'
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                mail = Mail.objects.create(
                    identifier="1",
                    headers={
                        'To': 'test@example.com',
                        'X-MAILSEND-Message-Id': '1'})
                workers = policies.mx.First().apply(mail.headers)
                worker_ranking = warm_up.Policy(
                    mail.identifier, mail.headers,
                    MailStatus).apply(workers)
                best_worker, next_available, *_ = policies.mx.Last().apply(
                    worker_ranking)
                self.assertEqual(best_worker.name, worker_01.name)
                self.assertEqual(best_worker.ip, worker_01.ip)

    def test_by_source_ip_disabled(self):
        worker = Worker.objects.create(
            name='worker_01', ip='10.0.0.1', policies_settings={
                'warm_up': {
                    'domain_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 0, 'max_tolerance': 0},
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 0, 'max_tolerance': 0,
                        'enabled': False}}})

        with fake_time('2015-12-09 12:00:00'):
            self.create_mails(worker, 5)

        with fake_time('2015-12-10 12:00:30'):
            mail = Mail.objects.create(identifier="1")
            workers = policies.mx.First().apply({'To': 'test@example.com'})
            worker_ranking = warm_up.Policy(
                mail.identifier, {'To': 'test@example.com'},
                MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
            self.assertEqual(best_worker.ip, worker.ip)

        with fake_time('2015-12-10 12:05:00'):
            self.create_mails(worker, 10, 'example.com', {
                'example.com': ('example.com')})
            MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
            MAILSEND_SETTINGS['WORKER_POLICIES'] = [
                'munch_mailsend.policies.mx.warm_up.Apply']
            MAILSEND_SETTINGS['WARM_UP_DOMAINS'] = {
                'example.com': ('example.com')}
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                mail = Mail.objects.create(identifier="2")
                workers = policies.mx.First().apply({'To': 'test@example.com'})
                worker_ranking = warm_up.Policy(
                    mail.identifier, {'To': 'test@example.com'},
                    MailStatus).apply(workers)
                best_worker, next_available, *_ = policies.mx.Last().apply(
                    worker_ranking)
                self.assertIsNone(best_worker)

                mail = Mail.objects.create(identifier="3")
                workers = policies.mx.First().apply(
                    {'To': 'test@example2.com'})
                worker_ranking = warm_up.Policy(
                    mail.identifier, {'To': 'test@example2.com'},
                    MailStatus).apply(workers)
                best_worker, next_available, *_ = policies.mx.Last().apply(
                    worker_ranking)
                self.assertEqual(best_worker.name, worker.name)
                self.assertEqual(best_worker.ip, worker.ip)

    def test_by_domains_list(self):
        worker = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={
                'warm_up': {
                    'domain_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 0, 'max_tolerance': 0},
                    'ip_warm_up': {
                        'matrix': [5, 10, 30, 50, 100], 'goal': 50,
                        'step_tolerance': 0, 'max_tolerance': 0,
                        'enabled': False}
                }
            })

        with fake_time('2015-12-10 12:00:00'):
            MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
            MAILSEND_SETTINGS['WARM_UP_DOMAINS'] = {
                'jambon': ('jambon.com', 'jambon.fr'),
                'gmail': ('gmail.com', 'gmail.fr')}
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                self.create_mails(worker, 5, destination_domain="gmail.com")

        with fake_time('2015-12-10 12:00:30'):
            MAILSEND_SETTINGS = copy.deepcopy(settings.MAILSEND)
            MAILSEND_SETTINGS['WARM_UP_DOMAINS'] = {
                'jambon': ('jambon.com', 'jambon.fr'),
                'gmail': ('gmail.com', 'gmail.fr')}
            with override_settings(MAILSEND=MAILSEND_SETTINGS):
                mail_metadata = Mail.objects.create(identifier="1")
                workers = policies.mx.First().apply({'To': 'test@gmail.fr'})
                worker_ranking = warm_up.Policy(
                    mail_metadata.identifier, {'To': 'test@gmail.fr'},
                    MailStatus).apply(workers)
                best_worker, *_ = policies.mx.Last().apply(
                    worker_ranking)
                self.assertIsNone(best_worker)

        with fake_time('2015-12-10 12:00:30'):
            mail_metadata = Mail.objects.create(identifier="2")
            workers = policies.mx.First().apply({'To': 'test@jambon.com'})
            worker_ranking = warm_up.Policy(
                mail_metadata.identifier, {'To': 'test@jambon.com'},
                MailStatus).apply(workers)
            best_worker, next_available, *_ = policies.mx.Last().apply(
                worker_ranking)
            self.assertEqual(best_worker.name, worker.name)
