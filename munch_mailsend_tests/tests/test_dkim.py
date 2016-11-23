import unittest

from munch_mailsend.models import Mail
from munch_mailsend.utils.dkim import verify
from munch_mailsend.policies.relay import dkim

from . import MailSendTestCase

DNS_TXT = (
    'v=DKIM1;t=s;p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDt7Nt5JM5cu/uh8izxLyT'
    'xYf5HhgGDOE20S4XxpgGOX14DetiDhTX4ziyELgip6sC4vOQWVx+uVkz2uuwd8QgY8N3MhJDc'
    'eyPpgXi73Er91d8WckY5Gh1exSkg5dCmz9GYzd1Ci1PXlX5mTN+90s5uYsLK1DLGhpsXFNdM5'
    'atGsQIDAQAB')


@unittest.skip('Must fix dkimpy to verify dkim signature')
class DKIMPolicyTestCase(MailSendTestCase):
    def test_dkim_verify(self):
        mail = Mail.objects.create(
            identifier='0001', message="My Body",
            headers={
                'To': 'test-to@example.com',
                'From': 'test-from@mailsend-test.com',
                'Subject': 'My Subject'})
        envelope = mail.as_envelope()
        signer = dkim.Sign()
        signer.apply(envelope)
        headers_data, message_data = envelope.flatten()
        self.assertTrue(verify(
            headers_data + b'\r\n' + message_data,
            dnsfunc=lambda name: DNS_TXT))
