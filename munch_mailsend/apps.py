from django.apps import AppConfig


class MailsendConfig(AppConfig):
    name = 'munch_mailsend'

    def ready(self):
        import munch_mailsend.signals  # noqa
