import logging

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Cache MailStatus'

    def add_arguments(self, parser):
        parser.add_argument('app_label', type=str)
        parser.add_argument('model_name', type=str)

    def handle(self, *args, **options):
        mailstatus_class = apps.get_model(
            options.get('app_label'), options.get('model_name'))
        count = mailstatus_class.objects.re_run_signals(
            settings.MAILSEND['MAILSTATUS_CACHE_TIMEOUT'])
        self.stdout.write(
            '{} MailStatus object(s) since {} second(s) have been '
            'cached. Done.'.format(
                count, settings.MAILSEND['MAILSTATUS_CACHE_TIMEOUT']))
