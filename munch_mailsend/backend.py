import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.utils.module_loading import import_string

from munch.core.mail.utils import extract_domain
from munch.core.mail.utils import mk_base64_uuid
from munch.core.mail.models import AbstractMailStatus

from .models import Mail
from .models import RawMail
from .tasks import route_envelope
from .utils import message_to_envelope

log = logging.getLogger(__name__)


class Backend(BaseEmailBackend):
    def __init__(
            self,
            build_envelope_task_path='mailsend.utils.tasks.get_envelope',
            mailstatus_class_path='mailsend.models.MailStatus',
            record_status_task_path='mailsend.utils.tasks.record_status',
            *args, **kwargs):
        self.mailstatus_class_path = mailstatus_class_path
        self.record_status_task_path = record_status_task_path
        self.build_envelope_task_path = build_envelope_task_path

        self.get_envelope = import_string(self.build_envelope_task_path)
        self.mailstatus_class = import_string(self.mailstatus_class_path)
        self.record_status_task = import_string(self.record_status_task_path)

        self.sandbox = settings.MAILSEND['SANDBOX']

    def _route(self, identifier, headers, attempts, priority=50):
        return route_envelope.apply_async(
            (identifier, headers, attempts), {
                'mailstatus_class_path': self.mailstatus_class_path,
                'record_status_task_path': self.record_status_task_path,
                'build_envelope_task_path': self.build_envelope_task_path},
            priority=priority).id

    def _handle_sandbox(self, identifier, recipient):
        log.info('Ignoring {} envelope because SANDBOX is enabled'.format(
            identifier))
        mailstatus = self.mailstatus_class(
            status=AbstractMailStatus.SENDING,
            destination_domain=extract_domain(recipient))
        self.record_status_task(
            mailstatus, identifier,
            settings.MAILSEND.get('SMTP_WORKER_EHLO_AS'))

    def send_envelope(self, envelope, attempts=0, priority=60):
        #
        # TODO: set priority using Customer reputation score
        # Best would be to call external modules (like munchers)
        # And keep transactional more prioritized than campaigns
        #
        identifier = envelope.headers.get(
            settings.MAILSEND['X_MESSAGE_ID_HEADER'])

        if self.sandbox:
            self._handle_sandbox(identifier, envelope.recipients[0])
            return
        return self._route(
            identifier, dict(envelope.headers), attempts, priority=priority)

    def send_message(self, identifier, recipient, headers, attempts=0):
        #
        # TODO: set priority using Customer reputation score
        # Best would be to call external modules (like munchers)
        #
        if self.sandbox:
            self._handle_sandbox(identifier, recipient)
            return
        return self._route(identifier, headers, attempts=attempts, priority=50)

    # To be used by Django as a standard email backend
    def send_messages(self, email_messages):
        if not email_messages:
            return
        num_sent = 0
        for message in email_messages:
            if self.send_simple_message(message, system=True):
                num_sent += 1
        return num_sent

    def send_simple_envelope(self, envelope, identifier=None, priority=50):
        if not identifier:
            identifier = envelope.headers.get(
                settings.MAILSEND['X_MESSAGE_ID_HEADER'])
            if identifier is None:
                identifier = mk_base64_uuid()
                envelope.headers.add_header(
                    settings.MAILSEND['X_MESSAGE_ID_HEADER'], identifier)

        raw_mail, created = RawMail.objects.get_or_create(
            content=envelope.message)
        mail = Mail.objects.create(
            identifier=identifier,
            headers=dict(envelope.headers), message=raw_mail,
            sender=envelope.sender, recipient=envelope.recipients[0])
        mailstatus = self.mailstatus_class(
            mail=mail, status=AbstractMailStatus.QUEUED,
            destination_domain=extract_domain(envelope.recipients[0]))

        self.record_status_task(
            mailstatus, identifier,
            settings.MAILSEND.get('SMTP_WORKER_EHLO_AS'))
        self.send_envelope(envelope, priority=priority)

    def send_simple_message(self, message, system=False):
        # Always send system and other simple messages (eg. message previews)
        # before others
        return self.send_simple_envelope(
            message_to_envelope(message), priority=100)
