from django.conf import settings
from slimta.policy import RelayPolicy


class StripBlacklisted(RelayPolicy):
    def apply(self, envelope):
        for header in settings.MAILSEND.get('BLACKLISTED_HEADERS', []):
            if header in envelope.headers:
                del envelope.headers[header]
