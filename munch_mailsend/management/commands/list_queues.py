import logging

from celery import current_app as app
from django.conf import settings
from django.core.management.base import BaseCommand
from amqp.exceptions import NotFound

from ...models import Worker
from ...amqp import get_queue
from ...amqp import get_queue_size

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'List all queues'

    def print_queue_line(self, name, details=''):
        try:
            queue = get_queue(self.connection, name)
            self.stdout.write(self.line_format.format(
                queue.name, get_queue_size(queue), details))
        except NotFound:
            self.print_not_found_queue(name)

    def print_worker_queue_line(self, worker, details='', retry=False):
        try:
            count = 0
            queue = worker.get_queue(self.connection, retry=retry)
            if self.scheduled_tasks:
                if self.scheduled_tasks:
                    for t in self.scheduled_tasks.get(worker.name):
                        if t.get('request', {}).get(
                                'delivery_info', {}).get(
                                'routing_key') == queue.name:
                            count += 1
            else:
                details += '(worker too busy to request scheduled tasks)'
            if count:
                details += '({} scheduled)'.format(count)
            self.stdout.write(self.line_format.format(
                queue.name, worker.get_queue_size(queue), details))
        except NotFound:
            self.print_not_found_queue(queue.name)

    def print_not_found_queue(self, name):
        self.stdout.write(self.line_format.format(
            name, 'n/a', self.style.ERROR('(not created)')))

    def handle(self, *args, **options):
        self.line_format = '{:35}: {} {}'
        self.connection = app.connection()
        self.print_queue_line(settings.CELERY_DEFAULT_QUEUE)
        self.print_queue_line(settings.MAILSEND.get('ROUTING_QUEUE'))
        self.print_queue_line(settings.MAILSEND.get(
            'QUEUED_MAIL_QUEUE'))

        self.stdout.write('')
        for worker in Worker.objects.all():
            self.scheduled_tasks = {}
            scheduled_tasks_count = 0
            while not any(
                    self.scheduled_tasks.values()) \
                    and scheduled_tasks_count <= 2:
                scheduled_tasks_count += 1
                self.scheduled_tasks = app.control.inspect(
                    [worker.name]).scheduled() or {}
            details = self.style.ERROR(
                '(disabled) ') if not worker.enabled else ''
            self.print_worker_queue_line(worker, details)
            self.print_worker_queue_line(worker, details, retry=True)
