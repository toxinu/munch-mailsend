from django.test import TestCase
from django.conf import settings
from libfaketime import reexec_if_needed
from django_redis import get_redis_connection

reexec_if_needed()


class MailSendTestCase(TestCase):
    def tearDown(self):
        conn = get_redis_connection()
        for key in conn.scan_iter('{}:*'.format(
                settings.MAILSEND['CACHE_PREFIX'])):
            conn.delete(key)
