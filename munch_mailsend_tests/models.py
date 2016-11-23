from django.db import models

from django.db.models.signals import pre_save
from django.db.models.signals import post_save

from munch.core.mail import backend

from munch_mailsend.models import RawMail
from munch_mailsend.models import MailStatus


class MailSendModel(models.Model):
    """
    Base for test models that sets app_label, so they play nicely.
    """
    class Meta:
        app_label = 'mailsend_tests'
        abstract = True


class AnotherMail(MailSendModel):
    message = models.ForeignKey(
        RawMail, on_delete=models.SET_NULL,
        null=True, related_name='test_anothermail')


class AgainAnotherMail(MailSendModel):
    message = models.ForeignKey(
        RawMail, on_delete=models.SET_NULL,
        null=True, related_name='test_mail')


pre_save.connect(backend.pre_save_mailstatus_signal, sender=MailStatus)
post_save.connect(backend.post_save_mailstatus_signal, sender=MailStatus)
