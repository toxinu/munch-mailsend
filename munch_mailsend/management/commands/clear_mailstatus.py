import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from django_redis import get_redis_connection

log = logging.getLogger(__name__)

conn = get_redis_connection('default')


class Command(BaseCommand):
    help = 'Clear MailStatus cache'

    def handle(self, *args, **options):
        count = 0
        for key in conn.scan_iter('{}:{}:*'.format(
                settings.MAILSEND['CACHE_PREFIX'],
                settings.MAILSEND['MAILSTATUS_CACHE_PREFIX'])):
            count += conn.delete(key)
        self.stdout.write(
            '{} key(s) deleted. Done.'.format(count))
