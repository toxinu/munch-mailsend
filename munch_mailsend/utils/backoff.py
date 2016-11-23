import math


class ExponentialBackOff:
    """ Configurable exponential Backoff function

    See https://slimta.org/latest/api/slimta.queue.html
    This one do not care about the envelope, only relies on timings

    Basic formula is A*e**n
    """
    _base = 250

    def __init__(self, retry_policy):
        """
        :param retry_policy: inspired by postfix retry settings, a 3-keys dict:
          - min_retry_interval: Minimum time (secs) between two retries
          - max_retry_interval: Maximum time (secs) between two retries
          - time_before_drop: Time (secs) before we drop the mail
            and notify the sender
        """
        try:
            self.min_retry_interval = retry_policy['min_retry_interval']
            self.max_retry_interval = retry_policy['max_retry_interval']
            self.time_before_drop = retry_policy['time_before_drop']
        except KeyError:
            raise KeyError(
                'RETRY_POLICY must define ''"min_retry_interval", '
                '"max_retry_interval" and "time_before_drop')
        # for cases where the min_retry_interval is under self._base
        # ensure the difference is always at least 1
        self.base = min(self._base, self.min_retry_interval - 1)
        self.A = self.get_A()

    def get_A(self):
        return (self.min_retry_interval - self.base) / math.e

    def delay(self, attempts):
        return min(
            self.A * math.e**attempts + self.base,
            self.max_retry_interval)

    def __call__(self, attempts):
        total_delay = sum(self.delay(i) for i in range(attempts))
        if total_delay <= self.time_before_drop:
            return int(self.delay(attempts))
        else:
            return None
