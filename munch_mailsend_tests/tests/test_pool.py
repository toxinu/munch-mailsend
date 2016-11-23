from libfaketime import fake_time

from munch_mailsend.models import Mail
from munch_mailsend.models import MailStatus
from munch_mailsend import policies
from munch_mailsend.models import Worker
from munch_mailsend.policies.mx import pool

from . import MailSendTestCase


class PoolPolicyTestCase(MailSendTestCase):
    def setUp(self):
        super().setUp()
        self.default_settings = {
            'pool': {
                'X_POOL_HEADER': 'X-MAILSEND-Pool',
                'pools': ['default']
            }
        }

    def test_pool(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings=self.default_settings)
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={
                'pool': {
                    'pools': ['jambon'],
                    'X_POOL_HEADER': 'X-MAILSEND-Pool'}})
        mail_metadata_01 = Mail.objects.create(identifier='0001')

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:05'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = pool.Policy(
                mail_metadata_01.identifier,
                {'To': 'test+01@example.com'},
                MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, score, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)
            self.assertEqual(score, 0.0)

    def test_pool_empty_list_is_default(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={'pool': {'X_POOL_HEADER': 'X-MAILSEND-Pool'}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={
                'pool': {
                    'pools': ['jambon'],
                    'X_POOL_HEADER': 'X-MAILSEND-Pool'}})
        mail_metadata_01 = Mail.objects.create(identifier='0001')

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:05'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = pool.Policy(
                mail_metadata_01.identifier,
                {'To': 'test+01@example.com'},
                MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, score, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)
            self.assertEqual(score, 0.0)

    def test_pool_no_match(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={
                'pool': {'X_POOL_HEADER': 'X-MAILSEND-Pool', 'pools': [
                    'jambon']}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={
                'pool': {'X_POOL_HEADER': 'X-MAILSEND-Pool', 'pools': [
                    'jambon']}})
        mail_metadata_01 = Mail.objects.create(identifier='0001')

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:05'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = pool.Policy(
                mail_metadata_01.identifier,
                {'To': 'test+01@example.com'},
                MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 0)

            best_worker, next_available, score, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertIsNone(best_worker)

    def test_pool_match_kk(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={
                'pool': {'X_POOL_HEADER': 'X-MAILSEND-Pool', 'pools': [
                    'jambon']}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={
                'pool': {
                    'pools': ['foo'],
                    'X_POOL_HEADER': 'X-MAILSEND-Pool'}})
        mail_metadata_01 = Mail.objects.create(
            identifier='0001', headers={'X-MAILSEND-Pool': 'jambon'})

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:05'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = pool.Policy(
                mail_metadata_01.identifier,
                {'To': 'test+01@example.com', 'X-MAILSEND-Pool': 'jambon'},
                MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, score, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)
            self.assertEqual(score, 0.0)

    def test_pool_match_insensitive(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={
                'pool': {'X_POOL_HEADER': 'X-MAILSEND-Pool', 'pools': [
                    'jambon']}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={
                'pool': {
                    'pools': ['foo'],
                    'X_POOL_HEADER': 'X-MAILSEND-Pool'}})
        mail_metadata_01 = Mail.objects.create(
            identifier='0001', headers={'X-MAILSEND-Pool': 'JAmbon'})

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:05'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = pool.Policy(
                mail_metadata_01.identifier,
                {'To': 'test+01@example.com', 'X-MAILSEND-Pool': 'JAmbon'},
                MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, score, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)
            self.assertEqual(score, 0.0)

    def test_pool_match_strip(self):
        worker_01 = Worker.objects.create(
            name='worker_01', ip='10.0.0.1',
            policies_settings={
                'pool': {'X_POOL_HEADER': 'X-MAILSEND-Pool', 'pools': [
                    'jambon']}})
        Worker.objects.create(
            name='worker_02', ip='10.0.0.2',
            policies_settings={
                'pool': {
                    'pools': ['foo'],
                    'X_POOL_HEADER': 'X-MAILSEND-Pool'}})
        mail_metadata_01 = Mail.objects.create(
            identifier='0001', headers={'X-MAILSEND-Pool': 'JAmbon  '})

        with fake_time('2015-12-10 12:00:00'):
            MailStatus.objects.create(
                destination_domain='example.com',
                mail=mail_metadata_01, source_ip=worker_01.ip)

        with fake_time('2015-12-10 12:00:05'):
            workers = policies.mx.First().apply({'To': 'test+01@example.com'})
            worker_ranking = pool.Policy(
                mail_metadata_01.identifier,
                {'To': 'test+01@example.com', 'X-MAILSEND-Pool': 'JAmbon  '},
                MailStatus).apply(workers)

            self.assertEqual(len(worker_ranking), 1)

            best_worker, next_available, score, *_ = policies.mx.Last().apply(
                worker_ranking)

            self.assertEqual(best_worker.name, worker_01.name)
            self.assertEqual(best_worker.ip, worker_01.ip)
            self.assertEqual(score, 0.0)
