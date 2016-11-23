from datetime import timedelta

from django_redis import get_redis_connection

from . import CACHE_PREFIX
from . import CACHE_TIMEOUT
from . import WorkerPolicyBase

conn = get_redis_connection('default')


class Policy(WorkerPolicyBase):
    """
        {'min_retry': 60 * 5}
    """
    def apply(self, workers):
        latest_status = self.get_latest(self.identifier)

        if not latest_status:
            self.logger.debug(
                '[{}] No previous status that represent a '
                'final state. Nothing to do...'.format(self.identifier))
            return workers

        if self.reply_message and 'greylist' in self.reply_message.lower():
            self.logger.debug(
                '[{}] Greylisting detected in reply message'.format(
                    self.identifier))
            now = self.now()
            for worker in workers:
                if worker.get('ip') == latest_status.get('source_ip'):
                    not_before = now + timedelta(
                        seconds=self.get_settings(worker).get(
                            'min_retry', 60 * 5))
                    self.logger.debug(
                        '[{}] This mail must be sent with {} not '
                        'before {}'.format(
                            self.identifier, worker, not_before.astimezone()))
                    worker['score'] += 0.5 * len(workers)
                    if not_before > worker.get('next_available'):
                        worker['next_available'] = not_before

        return workers

    @staticmethod
    def get_latest(identifier):
        value = conn.get('{}:greylist:{}'.format(
            CACHE_PREFIX, identifier))
        if not value:
            return {}
        splitted_value = value.decode('utf-8').split(':')
        return {
            'source_ip': splitted_value[0], 'creation_date': splitted_value[1]}

    ###########
    # Signals #
    ###########

    @staticmethod
    def mailstatus_pre_save(instance, manager):
        if instance.status in [instance.DELAYED]:
            conn.set('{}:greylist:{}'.format(
                CACHE_PREFIX, instance.mail.identifier),
                '{}:{}'.format(
                    instance.source_ip,
                    instance.creation_date.timestamp()), CACHE_TIMEOUT)
