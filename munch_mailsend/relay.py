import logging

from ssl import SSLContext
from ssl import PROTOCOL_SSLv23  # TODO: Switch to PROTOCOL_TLS with Py3.5.3+

from gevent.socket import create_connection
from django.conf import settings
from django.utils.module_loading import import_string
from slimta.relay.smtp.mx import MxSmtpRelay as MxSmtpRelayBase

log = logging.getLogger(__name__)


class RelayStartupFatalError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return 'FATAL, abording startup: {}'.format(self.msg)


def _socket_creator(address):
    return create_connection(
        address,
        source_address=(settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'), 0))


class MxSmtpRelay(MxSmtpRelayBase):
    def __init__(self, *args, **kwargs):
        self.ehlo = settings.MAILSEND.get('SMTP_WORKER_EHLO_AS')
        kwargs.setdefault('ehlo_as', self.ehlo)
        kwargs.setdefault('socket_creator', _socket_creator)

        ssl_context = SSLContext(PROTOCOL_SSLv23)
        kwargs.setdefault('context', ssl_context)

        for k, v in settings.MAILSEND.get('RELAY_TIMEOUTS', {}).items():
            kwargs.setdefault(k, v)

        # Add a binary_encoder if provided to convert utf-8 emails to ascii
        # for servers not supporting 8BITMIME
        kwargs.setdefault('binary_encoder', settings.MAILSEND.get(
            'BINARY_ENCODER'))

        super().__init__(*args, **kwargs)

        # Override MX lookups for specific configured domains
        # This might be used in Dev mode to avoid sending emails
        for force_mx in settings.MAILSEND.get('SMTP_WORKER_FORCE_MX', []):
            self.force_mx(**force_mx)

        self._add_settings_defined_policies()

    def _add_settings_defined_policies(self):
        for path in settings.MAILSEND.get('RELAY_POLICIES', []):
            try:
                policy = import_string(path)
            except ImportError:
                raise RelayStartupFatalError(
                    '{} points to inexistant policy'.format(path))
            except TypeError:
                raise RelayStartupFatalError(
                    '{} is not a valid RelayPolicy'.format(path))
            self.add_policy(policy())

    def attempt(self, envelope, *args, **kwargs):
        # Oddly, removing and re-adding the subject header prevents
        # bad encoding which result in utf-8 characters being encoded
        # like: =?unknown-8bit?q?
        # The documentation at https://docs.python.org/3.4/library/email.message.html#email.message.Message.add_header  # noqa
        # mentions that a header with non-ASCII character will be automatically
        # encoded using a utf-8 Charset. Likely related...
        # This should probably be addressed in Slimta though.
        subject = envelope.headers['Subject']
        del envelope.headers['Subject']
        envelope.headers.add_header('Subject', subject)
        # This is to avoid "Bare LF" errors (eg: with free.fr)
        # Probably not the cleanest way to do it but it works
        # TODO: see if this could be done upstream in envelope generation
        # or if slimta needs a fix (it should not let bare \n go through...)
        envelope.message = envelope.message.decode('utf-8').replace(
            '\n', '\r\n').encode('utf-8')
        # Attempt delivery as usual
        log.info('[{}] Attempting delivery from <{}> to <{}> ({})'.format(
            envelope.headers.get(
                settings.TRANSACTIONAL['X_MESSAGE_ID_HEADER'], 'unknown'),
            envelope.sender, ', '.join(envelope.recipients),
            envelope.headers['Subject']))
        return super().attempt(envelope, *args, **kwargs)
