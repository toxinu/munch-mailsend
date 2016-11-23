import logging

from celery import current_app as app
from django.core.management.base import BaseCommand

from ...models import Worker

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'List all worker messages'

    def add_arguments(self, parser):
        parser.add_argument('ip', nargs='+', type=str)
        parser.add_argument(
            '--limit', dest='limit', default=50, type=int,
            action='store', help="Message display limit (Default: 50)")

    def handle(self, *args, **options):
        class Counter:
            pass
        counter = Counter()
        counter.count = 0

        workers = Worker.objects.filter(ip__in=options['ip'])

        if not workers:
            print('Error: workers not found')

        self.scheduled_tasks = {}
        scheduled_tasks_count = 0
        while not any(
                self.scheduled_tasks.values()) and scheduled_tasks_count <= 2:
            scheduled_tasks_count += 1
            self.scheduled_tasks = app.control.inspect(
                [w.name for w in workers]).scheduled() or {}

        print('{:36};{:25};{:22};eta'.format(
            "task-id", "task-name", "message-id"))
        for worker in workers:
            if self.scheduled_tasks:
                scheduled_tasks = self.scheduled_tasks.get(worker.name)
                for t in scheduled_tasks:
                    r = t.get('request')
                    task_id = r.get('id')
                    task_name = r.get('name')
                    eta = t.get('eta')
                    identifier = eval(t.get('request').get('args'))[0]
                    print('{};{};{};{}'.format(
                        task_id, task_name, identifier, eta))
