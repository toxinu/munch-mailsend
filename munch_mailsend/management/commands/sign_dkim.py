import sys

from django.core.management.base import BaseCommand

from ...utils import dkim


class Command(BaseCommand):
    help = 'DKIM sign .eml'

    def add_arguments(self, parser):
        parser.add_argument('selector', type=str)
        parser.add_argument('domain', type=str)
        parser.add_argument('privatekeyfile', type=str)
        parser.add_argument('-i', '--identity', type=str, required=False)

    def handle(self, *args, **options):
        sys.stdin = sys.stdin.detach()
        sys.stdout = sys.stdout.detach()

        identity = options['identity']

        domain = options['domain'].encode('utf-8')
        selector = options['selector'].encode('utf-8')
        privatekeyfile = options['privatekeyfile']

        if identity:
            identity = identity.encode('utf-8')

        message = sys.stdin.read()
        try:
            HEADERS_TO_SIGN = [
                'From', 'Subject', 'Reply-To', 'To', 'Date',
                'Message-ID', 'List-ID', 'List-Unsubscribe',
                'Sender', 'Content-Type', 'MIME-Version']
            _ENCODED_HEADERS_TO_SIGN = [
                h.encode('utf-8') for h in HEADERS_TO_SIGN]
            sig = dkim.sign(
                message, selector, domain,
                open(privatekeyfile, "rb").read(),
                identity=identity, include_headers=_ENCODED_HEADERS_TO_SIGN)
            sys.stdout.write(sig + b'\n')
            sys.stdout.write(message)
        except Exception as e:
            raise
            print(e, file=sys.stderr)
            sys.stdout.write(message)
