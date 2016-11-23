from email.utils import parseaddr

from django.conf import settings
from slimta.policy import RelayPolicy

from munch.core.mail.utils import extract_domain

from ...utils.dkim import sign
from ...utils.dkim import DKIMException

# Headers must be Relaxed-Canonicalized
# because dkim doesn't do it automatically
DEFAULT_HEADERS_TO_SIGN = [
    'From', 'Subject', 'To', 'Date', 'Message-ID', 'Content-Type',
    'MIME-Version', settings.MAILSEND['X_USER_ID_HEADER'],
    settings.MAILSEND['X_MESSAGE_ID_HEADER']]


class Sign(RelayPolicy):
    def apply(self, envelope):

        # Copy without reference to avoid modifying default headers
        inc_headers = DEFAULT_HEADERS_TO_SIGN[:]
        # Add headers defined in settings
        for h in settings.MAILSEND.get('DKIM_EXTRA_SIGN_HEADERS', []):
            inc_headers.append(h)
        # Add extra headers to sign list if they are present
        # if not, we don't want to prevent them from being added later
        for h in ['Reply-To', 'List-ID', 'List-Unsubscribe', 'Sender']:
            if h in envelope.headers:
                inc_headers.append(h)
        encoded_inc_headers = [h.encode('utf-8') for h in inc_headers]

        identity = parseaddr(envelope.headers['From'])[1]
        domain = extract_domain(identity).encode('utf-8')

        try:
            headers_data, message_data = envelope.flatten()
            dkim_header = sign(
                headers_data + message_data,
                settings.MAILSEND.get('DKIM_SELECTOR', '').encode('utf-8'),
                domain,
                settings.MAILSEND.get('DKIM_PRIVATE_KEY', '').encode('utf-8'),
                identity=identity.encode('utf-8'), length=False,
                include_headers=encoded_inc_headers)
            dkim_header = dkim_header.decode('utf-8')
            if dkim_header.startswith('DKIM-Signature: '):
                dkim_header = dkim_header[16:]
                envelope.headers['DKIM-Signature'] = dkim_header
        except DKIMException:
            raise
