import pickle
import logging

from django.conf import settings
from django.db import models
from django.utils.module_loading import import_string
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

conn = get_redis_connection()


class WorkerManager(models.Manager):
    CACHE_PREFIX = 'workers'

    def find_worker(
            self, identifier, headers, mailstatus_class,
            not_before=None, reply=None):
        record_performance = settings.STATSD_ENABLED

        FirstPolicy = import_string('munch_mailsend.policies.mx.First')

        if record_performance:
            from statsd.defaults.django import statsd
            total_timer = statsd.timer('munch_mailsend.policies.mx.all')
            total_timer.start()

            timer = statsd.timer('munch_mailsend.policies.mx.First')
            timer.start()

        workers = FirstPolicy().apply(headers, not_before)

        if record_performance:
            timer.stop()

        for path in settings.MAILSEND.get('WORKER_POLICIES'):
            try:
                policy = import_string(path)
            except ImportError:
                raise ImportError(
                    '{} points to inexistant worker policy'.format(path))
            except TypeError:
                raise TypeError(
                    '{} is not a valid WorkerPolicy'.format(path))
            reply_code, reply_message = None, None
            if reply:
                reply_code, reply_message = reply.code, reply.message

            if record_performance:
                timer = statsd.timer(path)
                timer.start()

            workers = policy(
                identifier, headers,
                mailstatus_class, reply_code,
                reply_message, not_before).apply(workers)

            if record_performance:
                timer.stop()

        LastPolicy = import_string('munch_mailsend.policies.mx.Last')

        if record_performance:
            timer = statsd.timer('munch_mailsend.policies.mx.Last')
            timer.start()

        result = LastPolicy().apply(workers)

        if record_performance:
            timer.stop()
            total_timer.stop()

        return result

    def set_to_cache(self, worker):
        return conn.hset("{}:{}".format(
            settings.MAILSEND.get('CACHE_PREFIX'),
            self.CACHE_PREFIX),
            worker.ip, pickle.dumps({
                'pk': worker.pk,
                'ip': worker.ip,
                'name': worker.name,
                'policies_settings': worker.policies_settings}))

    def get_from_cache(self, ip=None):
        if ip:
            return pickle.loads(conn.hget(
                "{}:{}".format(
                    settings.MAILSEND.get('CACHE_PREFIX'),
                    self.CACHE_PREFIX, ip)))
        for worker in conn.hgetall("{}:{}".format(
                settings.MAILSEND.get('CACHE_PREFIX'),
                self.CACHE_PREFIX)).values():
            yield pickle.loads(worker)

    def remove_from_cache(self, worker):
        return conn.hdel("{}:{}".format(
            settings.MAILSEND.get('CACHE_PREFIX'),
            self.CACHE_PREFIX), worker.ip)

    def clear_cache(self):
        for key in conn.scan_iter('{}:{}'.format(
                settings.MAILSEND.get('CACHE_PREFIX'), self.CACHE_PREFIX)):
            conn.delete(key)
