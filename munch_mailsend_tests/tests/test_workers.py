from munch_mailsend.models import Worker
from munch_mailsend.policies.mx import First

from . import MailSendTestCase


class WorkersTestCase(MailSendTestCase):
    def test_retrieve_workers(self):
        Worker.objects.create(name='worker_01', ip='10.0.0.1')
        Worker.objects.create(name='worker_02', ip='10.0.0.2')

        workers = First().apply({})
        self.assertEqual(len(workers), 2)
        Worker.objects.clear_cache()
        workers = First().apply({})
        self.assertEqual(len(workers), 2)
