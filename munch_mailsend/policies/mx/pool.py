from django.conf import settings

from . import WorkerPolicyBase


class Policy(WorkerPolicyBase):
    """
        settings = {"pools": ['default']}
    """
    def apply(self, workers):
        available_workers = []
        x_pool_header = settings.MAILSEND['X_POOL_HEADER']
        pool = self.headers.get(x_pool_header, '').strip().lower()
        if not pool:
            pool = 'default'
            self.logger.debug(
                '[{}] No "{}" header found. Using: {}'.format(
                    self.identifier, x_pool_header, pool))
        else:
            self.logger.debug(
                '[{}] Found "{}" header with: {}'.format(
                    self.identifier, x_pool_header, pool))

        for worker in workers:
            worker_pools = self.get_settings(worker).get('pools', ['default'])

            if pool in worker_pools:
                self.logger.debug(
                    '[{}] [worker:{}] Pool: "{}" matched in {}'.format(
                        self.identifier, worker.get('ip'),
                        pool, worker_pools))
                available_workers.append(worker)
            else:
                self.logger.debug(
                    '[{}] [worker:{}] No pool matched for {} in {}.'.format(
                        self.identifier, worker.get('ip'), pool, worker_pools))
        return available_workers
