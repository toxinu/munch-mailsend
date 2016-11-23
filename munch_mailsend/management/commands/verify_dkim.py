import sys

from django.core.management.base import BaseCommand

from ...utils import dkim


class Command(BaseCommand):
    help = 'DKIM verify envelope'

    def handle(self, *args, **options):
        sys.stdin = sys.stdin.detach()
        message = sys.stdin.read()

        d = dkim.DKIM(message)
        res = d.verify()
        if not res:
            print("signature verification failed")
            sys.exit(1)
        print("signature ok")
