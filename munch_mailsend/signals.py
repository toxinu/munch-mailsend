from django.conf import settings

from .policies import run_policies


def pre_save_mailstatus(sender, instance, raw, **kwargs):
    # Default values
    if not instance.pk and not raw:
        if not instance.source_ip:
            instance.source_ip = settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR')
    # Policies
    if not instance.pk:
        run_policies(instance, 'mailstatus_pre_save')


def post_save_mailstatus(sender, instance, created, raw, **kwargs):
    # Policies
    if created:
        run_policies(instance, 'mailstatus_post_save')
