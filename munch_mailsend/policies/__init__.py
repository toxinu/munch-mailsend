from django.conf import settings
from django.utils.module_loading import import_string

from munch.core.mail.models import BaseMailStatusManager


def run_policies(mailstatus, method):
    for path in settings.MAILSEND.get('WORKER_POLICIES'):
        try:
            policy = import_string(path)
        except ImportError:
            raise ImportError(
                '{} points to inexistant worker policy'.format(path))
        except TypeError:
            raise TypeError(
                '{} is not a valid WorkerPolicy'.format(path))
        getattr(policy, method)(mailstatus, BaseMailStatusManager)
