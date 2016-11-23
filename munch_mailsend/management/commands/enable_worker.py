import logging

from django.core.management.base import BaseCommand

from ...models import Worker

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Disable worker'

    def add_arguments(self, parser):
        parser.add_argument('worker_id', nargs='+', type=str)

    def handle(self, *args, **options):
        for worker_id in options['worker_id']:
            try:
                worker = Worker.objects.get(pk=worker_id)
                worker.enabled = True
                worker.save()
                self.stdout.write(self.style.SUCCESS(
                    "* {} (pk:{}) enabled".format(worker.ip, worker.pk)))
            except ValueError:
                self.stdout.write(self.style.WARNING(
                    "* {} is not a valid Worker id.".format(worker_id)))
            except Worker.DoesNotExist:
                self.stdout.write(self.style.WARNING(
                    "* {} doesn't exist (ignored)".format(worker_id)))
