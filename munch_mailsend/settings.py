import os

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

WORKER_TYPE = os.environ.get('WORKER_TYPE')

DEFAULTS = {
    'RELAY_TIMEOUTS': {
        'connect_timeout': 30.0, 'command_timeout': 30.0,
        'data_timeout': None, 'idle_timeout': None},
    'CACHE_PREFIX': 'ms',
    'MAILSTATUS_CACHE_TIMEOUT': 60 * 60 * 24 * 15,
    'MAILSTATUS_CACHE_PREFIX': 'status',
    'TOKEN_CACHE_TIMEOUT': 60 * 60 * 24 * 10,
    'ROUTER_LOCK_TIMEOUT': 60 * 5,
    'ROUTER_LOCK_WAITING': 7,
    'MX_WORKER_MAX_PING_FAILURES': 10,
    'MX_WORKER_QUEUE_PREFIX': 'mailsend.mail.send.first:{ip}',
    'MX_WORKER_QUEUE_RETRY_PREFIX': 'mailsend.mail.send.retry:{ip}',
    'ROUTING_QUEUE': 'mailsend.mail.routing',
    'QUEUED_MAIL_QUEUE': 'mailsend.mail.queued',
    'RETRY_POLICY': {
        # Minimun time between two retries
        'min_retry_interval': 600,
        # Maximum time between two retries
        'max_retry_interval': 3600,
        # Time before we drop the mail and notify sender
        'time_before_drop': 2 * 24 * 3600},
    'BLACKLISTED_HEADERS': [],
    'RELAY_POLICIES': [
        'munch_mailsend.policies.relay.headers.StripBlacklisted',
        'munch_mailsend.policies.relay.dkim.Sign'],
    'WORKER_POLICIES': [
        'munch_mailsend.policies.mx.pool.Policy',
        'munch_mailsend.policies.mx.rate_limit.Policy',
        'munch_mailsend.policies.mx.greylist.Policy',
        'munch_mailsend.policies.mx.warm_up.Policy'],
    'SANDBOX': False,
    'TASKS_SETTINGS': {
        'send_email': {
            'default_retry_delay': 180,
            'max_retries': (2 * 7 * 24 * 60 * 60) / 180
        },
        'route_envelope': {
            'default_retry_delay': 180,
            'max_retries': (2 * 7 * 24 * 60 * 60) / 180
        }
    }
}

MANDATORY_SETTINGS = ['X_MESSAGE_ID_HEADER', 'X_POOL_HEADER']

if not hasattr(settings, 'MAILSEND'):
    setattr(settings, 'MAILSEND', DEFAULTS)

# Check RELAY_TIMEOUTS values
for key in settings.MAILSEND.get('RELAY_TIMEOUTS', {}):
    if key not in [
            'connect_timeout', 'command_timeout',
            'data_timeout', 'idle_timeout']:
        raise ImproperlyConfigured(
            '"RELAY_TIMEOUTS" doesn\'t recognize "{}" value.'.format(key))

# Check settings for MX workers
if WORKER_TYPE in ['all', 'mx']:
    # Check if EHLO_AS and SRC_ADDR are correctly set
    if not settings.MAILSEND.get('SMTP_WORKER_EHLO_AS'):
        raise ImproperlyConfigured(
            'Missing "MAILSEND"[\'SMTP_WORKER_EHLO_AS\'] setting.')
    if not settings.MAILSEND.get('SMTP_WORKER_SRC_ADDR'):
        raise ImproperlyConfigured(
            'Missing "MAILSEND"[\'SMTP_WORKER_SRC_ADDR\'] setting.')
    # Check if DKIM_SELECTOR and DKIM_PRIVATE_KEY are set
    # if dkim policy is enabled
    if 'munch_mailsend.policies.relay.dkim.Sign' in settings.MAILSEND.get(
            'RELAY_POLICIES', []):
        if not settings.MAILSEND.get('DKIM_SELECTOR'):
            raise ImproperlyConfigured(
                'Must set "DKIM_SELECTOR" if '
                ""'mailsend.policies.mx.dkim" mx policy is used.')
        if not settings.MAILSEND.get('DKIM_PRIVATE_KEY'):
            raise ImproperlyConfigured(
                'Must set "DKIM_PRIVATE_KEY" if '
                '"mailsend.policies.mx.dkim" mx policy is used.')


# These settings should be defined on every node type
for field in MANDATORY_SETTINGS:
    if settings.MAILSEND.get(field, None) is None:
        raise ImproperlyConfigured('Missing "MAILSEND[\'{}\']" setting'.format(
            field))

# Set some defaults
for field in DEFAULTS:
    settings.MAILSEND.setdefault(field, DEFAULTS[field])
