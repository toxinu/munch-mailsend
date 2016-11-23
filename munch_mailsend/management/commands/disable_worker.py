import logging

from celery import current_app as app
from django.core.management.base import BaseCommand

from ...models import Worker

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Remotely shutdown worker.'

    def add_arguments(self, parser):
        parser.add_argument('worker_id', nargs='+', type=str)

    def handle(self, *args, **options):
        for worker_id in options['worker_id']:
            try:
                worker = Worker.objects.get(pk=worker_id)
                self.stdout.write('Saving worker as disabled...')
                worker.enabled = False
                worker.save()
                self.stdout.write('Sending shutdown event to worker...')
                app.control.broadcast('shutdown', destination=(worker.name,))
            except Worker.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    "* {} doesn't exist (ignored)".format(worker_id)))
