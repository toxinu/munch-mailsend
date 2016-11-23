from munch.settings.test import *

INSTALLED_APPS += ['munch_mailsend_tests', ]

##########
# Global #
##########
MASS_EMAIL_BACKEND = 'munch_mailsend.backend.Backend'

##################
# Custom headers #
##################
X_POOL_HEADER = 'X-CM-Pool'
X_USER_ID_HEADER = 'X-CM-User-Id'

############
# Mailsend #
############
MAILSEND = {
    # All Internal mailsend emails will be send to a blackhole
    'SANDBOX': True,
    'RELAY_TIMEOUTS': {
        'connect_timeout': 30.0, 'command_timeout': 30.0,
        'data_timeout': None, 'idle_timeout': None},
    # Timeout for MailStatus cache
    'MAILSTATUS_CACHE_TIMEOUT': 60 * 60 * 24 * 15,
    'X_POOL_HEADER': X_POOL_HEADER,
    'X_USER_ID_HEADER': X_USER_ID_HEADER,
    'X_MESSAGE_ID_HEADER': X_MESSAGE_ID_HEADER,
    # Letting to None will make it use the host FQDN
    'SMTP_WORKER_EHLO_AS': 'localhost',
    # Letting to None fallback to system routing
    # example: '1.2.3.4'
    'SMTP_WORKER_SRC_ADDR': '127.0.0.1',
    # Backoff time is exponentially growing up to max_retry_interval and then
    # staying there on each retry till we reach time_before_drop.
    'RETRY_POLICY': {
        # Minimun time between two retries
        'min_retry_interval': 600,
        # Maximum time between two retries
        'max_retry_interval': 3600,
        # Time before we drop the mail and notify sender
        'time_before_drop': 2 * 24 * 3600},
    'BINARY_ENCODER': None,
    'BLACKLISTED_HEADERS': [
        X_POOL_HEADER,
        X_HTTP_DSN_RETURN_PATH_HEADER,
        X_SMTP_DSN_RETURN_PATH_HEADER],
    'RELAY_POLICIES': [
        'munch.apps.transactional.policies.relay.headers.RewriteReturnPath',
        'munch_mailsend.policies.relay.headers.StripBlacklisted',
        'munch_mailsend.policies.relay.dkim.Sign'],
    'WORKER_POLICIES': [
        'munch_mailsend.policies.mx.pool.Policy',
        'munch_mailsend.policies.mx.rate_limit.Policy',
        'munch_mailsend.policies.mx.greylist.Policy',
        'munch_mailsend.policies.mx.warm_up.Policy'],
    'WORKER_POLICIES_SETTINGS': {
        'rate_limit': {'domains': [(r'.*', 2)], 'max_queued': 60 * 15},
        'warm_up': {
            'prioritize': 'equal',
            'domain_warm_up': {
                'matrix': [50, 100, 300, 500, 1000],
                'goal': 500,
                'max_tolerance': 10,
                'step_tolerance': 10,
                'days_watched': 10,
            },
            'ip_warm_up': {
                'matrix': [50, 100, 300, 500, 1000],
                'goal': 500,
                'max_tolerance': 10,
                'step_tolerance': 10,
                'enabled': False,
                'days_watched': 10,
            }
        },
        'pool': {'pools': ['default']},
        'greylist': {'min_retry': 60 * 5},
    },
    'WARM_UP_DOMAINS': {},
    # Fake DKIM private key for tests
    'DKIM_PRIVATE_KEY': """-----BEGIN RSA PRIVATE KEY-----
MIICXQIBAAKBgQC1Lgr+47aZ+dWFyfq/pRrgC0eL4dR4KwX19JvrTuYtS+Wp4Pw2
Oov40V37EHOLPQIXUhdVGanvsTHAsBpIG4W8Uf9cUq6zRpljcirHZ4rv+8lGcb1n
QYB9YEqepEQli6/kgDIw+stDAfZTY/jLzweaIgj9nyLoCpYcZ5jBRpzTcwIDAQAB
AoGBAJ135xah05MAERS297iZR0JyizyIiqHmwseCUgGyEVxNGs8LPCnluMIJNiV/
puzdmXOrZZwRMiGhYByY8j65rQEIVWKB5e2eRC/Of8Sy5o+8cyVqAfA5MXFcZcxZ
9gzEoc6NT4SYE3DhaaLphg1f7hjmkzEmyQygenFS5XHD+EQBAkEA6/pz4JfKynjW
9dHlCH3wC44Ke6btg6Dixnnp34dso0eY9Hqys0lU6JMkiGRT5aSmA24RbS1gqQMt
cD7NfgroHwJBAMSNWDuwAcdD3YQv8/oupE+3Dhhtg0F2IuFVabIHn1TtGUjZWri6
17abiodnoyy2+hEs7/Yn7CgDm8c2jTKFOi0CQELZstYfal2tmggNrDqZotVDKgkZ
oxO1Eklz5CNk9AvVjqlD0TglQB6bALB666GU4Ur7dYheYJHAyrCPuhtI77UCQEqb
DB671DD6xZ5jRUx1X9ESPrtu9h9m5B57+T6mPghSZwKL3i+4XCDoMVDsObfDTHAw
inT4+l7F399iCX5fq5ECQQCTo6leuSjIQ1wfnt/JVUcsJX6AX2H/lsNmGxbLl+Wo
Jkz+iJs15bXpdRzcHqVqVy5mg23Cb2LfQ9rAsW/vzX3L
-----END RSA PRIVATE KEY-----""",
    'DKIM_SELECTOR': 'tests',
    'TLS': {'keyfile': None, 'certfile': None},
}

#################
# Transactional #
#################
TRANSACTIONAL['HEADERS_TO_REMOVE'] += [X_POOL_HEADER]
