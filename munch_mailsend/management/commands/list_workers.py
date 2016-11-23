import logging

from django.core.management.base import BaseCommand

from ...models import Worker

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'List all workers'

    def handle(self, *args, **options):
        for worker in Worker.objects.all():
            color = self.style.SUCCESS if worker.enabled else self.style.ERROR
            self.stdout.write(color(
                '* {} (pk:{})'.format(worker.ip, worker.pk, worker.enabled)))
            print('├────────────── Details ──────────────')
            print('├─ Enabled: {}'.format(worker.enabled))
            print('├─ Name: {}'.format(worker.name))
            print('├─ Creation date: {}'.format(worker.creation_date))
            print('├─ Update date: {}'.format(worker.update_date))
            print('└─────────────────────────────────────')
