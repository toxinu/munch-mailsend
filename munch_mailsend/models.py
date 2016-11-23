from django.db import models
from django.contrib.postgres.fields import JSONField
from django.contrib.postgres.fields import HStoreField
from django.utils.translation import ugettext_lazy as _
from slimta.envelope import Envelope
from kombu import Queue
from kombu import Exchange

from munch.core.mail.utils import mk_base64_uuid
from munch.core.mail.models import RawMail
from munch.core.mail.models import AbstractMail
from munch.core.mail.models import AbstractMailStatus

from .settings import settings
from .managers import WorkerManager


class Worker(models.Model):
    name = models.CharField(
        max_length=100,
        help_text="Celery worker name (nothing related with SMTP EHLO)")
    ip = models.GenericIPAddressField(unique=True)
    creation_date = models.DateTimeField(auto_now_add=True)
    update_date = models.DateTimeField(auto_now=True)
    enabled = models.BooleanField(default=True)
    policies_settings = JSONField(null=True, blank=True)

    objects = WorkerManager()

    def __str__(self):
        return '{} ({})'.format(self.name, self.ip)

    def get_queue_name(self, retry=False):
        base = settings.MAILSEND.get('MX_WORKER_QUEUE_PREFIX')
        if retry:
            base = settings.MAILSEND.get('MX_WORKER_QUEUE_RETRY_PREFIX')
        return base.format(ip=self.ip)

    def get_queue(self, connection, retry=False):
        exchange = Exchange(
            channel=connection,
            name=settings.CELERY_DEFAULT_EXCHANGE,
            type=settings.CELERY_DEFAULT_EXCHANGE_TYPE)
        return Queue(self.get_queue_name(
            retry=retry), exchange=exchange).bind(connection)

    def get_queue_size(self, queue):
        return queue.queue_declare(passive=True).message_count

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.enabled:
            WorkerManager().set_to_cache(self)
        else:
            WorkerManager().remove_from_cache(self)


def get_mail_identifier():
    return mk_base64_uuid('i-')


class Mail(AbstractMail):
    identifier = models.CharField(
        max_length=35, db_index=True, unique=True,
        default=get_mail_identifier, verbose_name=_('identifier'))
    headers = HStoreField(default={})
    sender = models.EmailField()
    message = models.ForeignKey(RawMail, on_delete=models.SET_NULL, null=True)

    @classmethod
    def get_envelope(cls, identifier):
        from .utils.tasks import get_envelope
        return get_envelope(identifier)

    def as_envelope(self):
        envelope = Envelope()
        headers = ""
        for key, value in self.headers.items():
            headers += "{}: {}\n".format(key, value)
        if self.message is None:
            raise Exception(
                "Can't build this envelope because "
                "there is no RawMail attached to it.")
        message = self.message.content or ""
        envelope.parse(headers.encode('utf-8') + message.encode('utf-8'))
        envelope.sender = self.sender
        envelope.recipients.append(self.recipient)
        return envelope


class MailStatus(AbstractMailStatus):
    mail = models.ForeignKey(Mail)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.status in self.FINAL_STATES:
            self.mail.message = None
            self.mail.save()
