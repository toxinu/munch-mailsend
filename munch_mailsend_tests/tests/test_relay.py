from django.test import override_settings

from munch_mailsend.relay import MxSmtpRelay

from . import MailSendTestCase


class RelayTestCase(MailSendTestCase):
    @override_settings(MAILSEND={'SMTP_WORKER_EHLO_AS': None})
    def test_default_relay_ehlo(self):
        relay = MxSmtpRelay()
        self.assertEqual(relay._client_kwargs['ehlo_as'], None)

    @override_settings(MAILSEND={'SMTP_WORKER_EHLO_AS': 'test12'})
    def test_override_relay_ehlo(self):
        relay = MxSmtpRelay()
        self.assertEqual(relay._client_kwargs['ehlo_as'], 'test12')
