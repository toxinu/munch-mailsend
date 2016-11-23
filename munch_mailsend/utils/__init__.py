from functools import wraps

from django.conf import settings
from slimta.envelope import Envelope

from .backoff import *  # noqa


def message_to_envelope(message):
    generated_message = message.message()
    envelope = Envelope()
    envelope.parse(generated_message.as_bytes())
    envelope.sender = message.from_email
    envelope.recipients.append(message.to[0])
    return envelope


def save_timer(name):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if settings.STATSD_ENABLED:
                from statsd.defaults.django import statsd
                timer = statsd.timer(name)
                timer.start()
            result = f(*args, **kwargs)
            if settings.STATSD_ENABLED:
                timer.stop()
            return result
        return wrapper
    return decorator
