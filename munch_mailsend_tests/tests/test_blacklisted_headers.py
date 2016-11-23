from django.conf import settings
from django.test import override_settings

from munch_mailsend.models import Mail
from munch_mailsend.models import RawMail
from munch_mailsend.policies.relay import headers

from . import MailSendTestCase


class BlacklistedHeadersTestCase(MailSendTestCase):
    @override_settings(MAILSEND={'BLACKLISTED_HEADERS': ['jambon']})
    def test_blacklisted_headers(self):
        raw_mail, _ = RawMail.objects.get_or_create(content='My Body')
        mail = Mail.objects.create(
            identifier='0001', message=raw_mail,
            headers={'To': 'foo@bar', 'jambon': 'My Jambonnery year'})
        envelope = mail.as_envelope()
        cleaner = headers.StripBlacklisted()
        cleaner.apply(envelope)
        for field in settings.MAILSEND['BLACKLISTED_HEADERS']:
            self.assertNotIn(field, envelope.headers)

    @override_settings(MAILSEND={'BLACKLISTED_HEADERS': ['jaMbon']})
    def test_blacklisted_headers_insensitive_case(self):
        raw_mail, _ = RawMail.objects.get_or_create(content='My Body')
        value = 'My Jambonnnery yea'
        mail = Mail.objects.create(
            identifier='0001', message=raw_mail,
            headers={'To': 'foo@bar', 'jambon': value})
        envelope = mail.as_envelope()
        cleaner = headers.StripBlacklisted()
        cleaner.apply(envelope)
        for field in settings.MAILSEND['BLACKLISTED_HEADERS']:
            self.assertNotIn(field, envelope.headers)
        self.assertNotIn('jambon', envelope.headers)
