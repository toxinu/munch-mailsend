from django.conf import settings

settings.MAILSEND['X_POOL_HEADER'] = 'X-MAILSEND-Pool'
settings.MAILSEND['WORKER_POLICIES_SETTINGS'] = {
    'rate_limit': {'domains': [(r'.*', 2)], 'max_queued': 60 * 15},
    'warm_up': {
        'prioritize': 'equal',
        'domain_warm_up': {
            'matrice': [50, 100, 300, 500, 1000],
            'goal': 500,
            'max_tolerance': 10,
            'step_tolerance': 10,
            'domains_list': []},
        'ip_warm_up': {
            'matrice': [50, 100, 300, 500, 1000],
            'goal': 500,
            'max_tolerance': 10,
            'step_tolerance': 10,
            'enabled': False
        }
    }
}
