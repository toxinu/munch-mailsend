import uuid
import socket
import logging
from random import randint
from datetime import timedelta

from celery import task
from celery import current_app
from django.conf import settings
from django.db import connection
from django.utils import timezone
from django.utils.module_loading import import_string
from slimta.smtp.reply import Reply
from slimta.relay.smtp.mx import PermanentRelayError
from slimta.relay.smtp.mx import TransientRelayError
from django_redis import get_redis_connection

from munch.core.mail.utils import extract_domain
from munch.core.utils.tasks import task_autoretry
from munch.core.mail.models import AbstractMailStatus
from munch.core.mail.exceptions import SoftFailure
from munch.core.utils import get_worker_types

from .utils import save_timer
from .utils import ExponentialBackOff
from .utils.tasks import acquire_lock
from .utils.tasks import release_lock
from .models import Worker
from .amqp import get_queue
from .amqp import get_queue_size
from .relay import MxSmtpRelay

log = logging.getLogger(__name__)
conn = get_redis_connection()
worker_types = get_worker_types()


@task_autoretry(
    autoretry_on=(Exception, ),
    default_retry_delay=settings.MAILSEND['TASKS_SETTINGS'][
        'send_email']['default_retry_delay'],
    max_retries=settings.MAILSEND['TASKS_SETTINGS'][
        'send_email']['max_retries'],
    retry_message='Error while trying to send email. Retrying.')
@save_timer(name='mailsend.tasks.send_email')
def send_email(
        identifier, headers, attempts, mailstatus_class_path,
        record_status_task_path, build_envelope_task_path, token=None):
    # Retrieve MailStatus class and record_status task
    mailstatus_class = import_string(mailstatus_class_path)
    record_status_task = import_string(record_status_task_path)
    build_envelope_task = import_string(build_envelope_task_path)

    # Helper to create a new MailStatus
    def record_new_status(status, identifier, headers, reply, ehlo):
        log.debug('[{}] [worker:{}] Recording "{}" status...'.format(
            identifier, settings.MAILSEND['SMTP_WORKER_SRC_ADDR'], status))
        mailstatus_kwargs = {}

        raw_message = ''
        if reply.code:
            raw_message += reply.code + ' '
        if reply.raw_message:
            raw_message += reply.raw_message

        if raw_message:
            mailstatus_kwargs.update({'raw_msg': raw_message.strip()})

        if reply.enhanced_status_code:
            mailstatus_kwargs.update(
                {'status_code': reply.enhanced_status_code})

        mailstatus = mailstatus_class(
            status=status,
            destination_domain=extract_domain(headers.get('To')),
            **mailstatus_kwargs)
        # Status recording needs to happen locally and synchronously:
        #   - status needs to be available immediately for future routing
        #   - Creation of object derived from AbstractMailStatus
        #     will use the local worker IP address as source
        #     (although we could pass it)
        try:
            record_status_task(mailstatus, identifier, ehlo, reply)
        except SoftFailure as exc:
            log.info(
                'SoftFailure during "send_email" task ('
                'discarding this task): {}'.format(str(exc)), exc_info=True)
            return
        if status in AbstractMailStatus.FINAL_STATES:
            delete_envelope_token(identifier)

    # Helper to properly handle a transient failure
    def handle_transient_failure(
            identifier, headers, attempts, reply, ehlo):
        log.debug(
            '[{}] Handling transient failure ({} {})'
            ' (attempts:{}).'.format(
                identifier, reply.code, reply.message, attempts))
        backoff = ExponentialBackOff(settings.MAILSEND.get('RETRY_POLICY'))
        wait = backoff(attempts + 1)
        if wait:
            not_before = timezone.now() + timedelta(seconds=wait)
            record_new_status(
                AbstractMailStatus.DELAYED,
                identifier, headers, reply, ehlo)
            route_envelope.apply_async(
                (
                    identifier, headers,
                    attempts + 1,
                    mailstatus_class_path,
                    record_status_task_path,
                    build_envelope_task_path),
                {'not_before': not_before, 'reply': reply})
        else:
            reply.message += ' (Too many retries)'
            record_new_status(
                AbstractMailStatus.DROPPED, identifier, headers, reply, ehlo)

    if not any([t in worker_types for t in ['mx', 'all']]):
        countdown = 60 * 10
        log.error(
            '[{}] [worker:{}] Received "send_email" task but '
            'this is not an MX worker ({}) (re-routing in {} minutes)'.format(
                identifier,
                settings.MAILSEND['SMTP_WORKER_SRC_ADDR'],
                worker_type, countdown / 60))
        reply = Reply(
            '450',
            (
                '4.0.0 Unhandled delivery error: Re-trying to send '
                'envelope in {} minutes.').format(countdown / 60))
        ehlo = settings.MAILSEND['SMTP_WORKER_SRC_ADDR']
        record_new_status(
            AbstractMailStatus.DELAYED, identifier, headers, reply, ehlo)
        route_envelope.apply_async(
            (
                identifier, headers, attempts,
                mailstatus_class_path,
                record_status_task_path,
                build_envelope_task_path),
            {'not_before': None, 'reply': None},
            countdown=countdown)
        return

    # Envelope with final states must be discards
    latest_status = mailstatus_class.objects.filter(
        status__in=[AbstractMailStatus.DELETED] +
        list(AbstractMailStatus.FINAL_STATES), mail__identifier=identifier)
    if latest_status:
        log.debug(
            "[{}] Envelope ignored because it has already been "
            "{} at {}".format(
                identifier, latest_status[0].status,
                latest_status[0].creation_date))
        return

    # If envelope doesn't have token in cache, there is a serious problem
    current_token = get_envelope_token(identifier)
    if current_token is None:
        reply = Reply(
            '450',
            '4.0.0 Unhandled delivery error: No envelope token found in cache')
        handle_transient_failure(
            identifier, headers, attempts,
            reply, settings.MAILSEND.get('SMTP_WORKER_EHLO_AS'))
        log.error(
            "[{}] Error while trying to get envelope token. "
            "Envelope will be re-routed.".format(identifier), exc_info=True)
        return
    # If token mismatch, maybe this task is a duplicate (problem incoming)
    if token != current_token:
        log.info(
            "[{}] Discarding these send_email task "
            "because token doesn't match")
        return
    log.debug('[{}] Token is valid: {}'.format(identifier, token))

    if attempts:
        log.debug(
            '[{}] [worker:{}] Retrying to send (attempts:{}) '
            '(from:{}) (to:{})...'.format(
                identifier, settings.MAILSEND['SMTP_WORKER_SRC_ADDR'],
                attempts, headers['From'], headers['To']))
    else:
        log.debug(
            '[{}] [worker:{}] Sending envelope '
            '(from:{}) (to:{})...'.format(
                identifier, settings.MAILSEND['SMTP_WORKER_SRC_ADDR'],
                headers['From'], headers['To']))

    try:
        relay = MxSmtpRelay()
        # We call parent (slimta.relay.Relay) _attempt()
        # to run relay policies
        try:
            envelope = build_envelope_task(identifier)
        except SoftFailure as exc:
            log.info(
                'SoftFailure during "send_email" task ('
                'discarding this task): {}'.format(str(exc)), exc_info=True)
            return
        reply = relay._attempt(envelope, attempts)
        # We assume single-recipient
        if isinstance(reply, (list, tuple)):
            reply = reply[0]
        elif isinstance(reply, dict):
            reply = list(reply.values())[0]
    except TransientRelayError as exc:
        handle_transient_failure(
            identifier, headers, attempts, exc.reply, relay.ehlo)
    except PermanentRelayError as exc:
        log.debug(
            '[{}] [worker:{}] Handling PermanentRelayError'
            'with reply: {}'.format(
                identifier,
                settings.MAILSEND['SMTP_WORKER_SRC_ADDR'],
                exc.reply))
        record_new_status(
            AbstractMailStatus.BOUNCED,
            identifier, headers, exc.reply, relay.ehlo)
    except (Exception, BrokenPipeError, IOError, OSError) as exc:
        reply = Reply('450', '4.0.0 Unhandled delivery error: ' + str(exc))
        handle_transient_failure(
            identifier, headers, attempts, reply, relay.ehlo)
        log.error(
            "[{}] Error while trying to send email via Slimta. "
            "Envelope will be re-routed.".format(
                identifier), exc_info=True)
    else:
        record_new_status(
            AbstractMailStatus.DELIVERED,
            identifier, headers, reply, relay.ehlo)


@task_autoretry(
    autoretry_on=(Exception, ),
    default_retry_delay=settings.MAILSEND['TASKS_SETTINGS'][
        'route_envelope']['default_retry_delay'],
    max_retries=settings.MAILSEND['TASKS_SETTINGS'][
        'route_envelope']['max_retries'],
    retry_message='Error while trying to route envelope. Retrying.')
@save_timer(name='mailsend.tasks.route_envelope')
def route_envelope(
        identifier, headers, attempts, mailstatus_class_path,
        record_status_task_path, build_envelope_task_path,
        not_before=None, reply=None):
    """
        This envelope routing task take initiate attempt
        to free Slimta Edge from SMTP connection
    """
    record_performance = settings.STATSD_ENABLED

    lock = None
    mailstatus_class = import_string(mailstatus_class_path)
    latest_status = mailstatus_class.objects.filter(
        status__in=[AbstractMailStatus.DELETED] +
        list(AbstractMailStatus.FINAL_STATES), mail__identifier=identifier)
    if latest_status:
        log.debug(
            "[{}] Envelope ignored because it has already been "
            "{} at {}".format(
                identifier, latest_status[0].status,
                latest_status[0].creation_date))
        return
    # Ensure we close Django database connection because we don't
    # want to have opened connections while waiting for lock.
    connection.close()

    destination_domain = extract_domain(headers.get('To', ''))

    pool = headers.get(settings.MAILSEND['X_POOL_HEADER'], 'default')

    lock_name = '{}:lock:routing:{}:{}'.format(
        settings.MAILSEND['CACHE_PREFIX'], destination_domain, pool)
    lock_timeout = settings.MAILSEND['ROUTER_LOCK_TIMEOUT']
    lock_blocking_timeout = settings.MAILSEND['ROUTER_LOCK_WAITING']
    log.debug(
        '[{}] Waiting for lock "{}" (timeout:{} '
        'second(s) and blocking for {} second(s))...'.format(
            identifier, lock_name, lock_timeout, lock_blocking_timeout))

    if record_performance:
        from statsd.defaults.django import statsd
        lock_timer = statsd.timer('mailsend.tasks.lock_waiting')
        lock_timer.start()

    lock = acquire_lock(
        lock_name, timeout=lock_timeout,
        blocking_timeout=lock_blocking_timeout)

    if record_performance:
        lock_timer.stop()

    if lock:
        try:
            log.debug('[{}] Routing envelope (attempts={})...'.format(
                identifier, attempts))

            worker, next_available, score, others = Worker.objects.find_worker(
                identifier, headers, mailstatus_class,
                not_before=not_before, reply=reply)
            if worker:
                log.debug(
                    '[{}] Choosen worker is available at {} '
                    'with a {} score. Full workers ranking: {}'.format(
                        identifier, next_available.astimezone(), score, {
                            w.get('ip'): {
                                'score': w.get('score'),
                                'next_available': str(
                                    w.get('next_available').astimezone())}
                            for w in others}))
                mail_status_kwargs = {
                    'source_ip': worker.ip,
                    'status': AbstractMailStatus.SENDING,
                    'destination_domain': extract_domain(
                        headers.get('To'))}
                if not attempts:
                    routing_key = worker.get_queue_name()
                else:
                    routing_key = worker.get_queue_name(retry=True)

                attempt = send_email.s(
                    identifier, headers, attempts,
                    mailstatus_class_path,
                    record_status_task_path,
                    build_envelope_task_path,
                    token=set_envelope_token(identifier))
                now = timezone.now()
                if next_available:
                    countdown = max(0, (next_available - now).total_seconds())
                # And apply countdown to task if > 0
                if countdown:
                    mail_status_kwargs.update({
                        'creation_date': now + timedelta(seconds=countdown)})
                    attempt.set(countdown=countdown)

                log.info(
                    '[{}] Queued with "{}" routing key in {} seconds'.format(
                        identifier, routing_key, int(countdown)))
                mailstatus = mailstatus_class(**mail_status_kwargs)
                record_status_task = import_string(record_status_task_path)
                try:
                    record_status_task(mailstatus, identifier, attempts + 1)
                except SoftFailure as exc:
                    log.info(
                        'SoftFailure during "route_envelope" task ('
                        'discarding this task): {}'.format(
                            str(exc)), exc_info=True)
                    release_lock(lock_name)
                    return

                release_lock(lock_name)

                return attempt.apply_async(routing_key=routing_key).id
            else:
                log.debug(
                    '[{}] No worker available. Re-route envelope '
                    'in 5 minutes'.format(identifier))
                release_lock(lock_name)
                return route_envelope.apply_async(
                    (
                        identifier, headers, attempts,
                        mailstatus_class_path,
                        record_status_task_path,
                        build_envelope_task_path),
                    {'not_before': not_before, 'reply': reply},
                    countdown=60 * 5).id
        except Exception:
            release_lock(lock_name)
            raise
    else:
        log.debug(
            '[{}] Failed to acquire lock after waiting {} second(s). '
            'Re-route task in 1-6 seconds.'.format(
                identifier, lock_blocking_timeout))
        return route_envelope.apply_async(
            (identifier, headers, attempts),
            {
                'mailstatus_class_path': mailstatus_class_path,
                'record_status_task_path': record_status_task_path,
                'build_envelope_task_path': build_envelope_task_path,
                'not_before': not_before, 'reply': reply},
            countdown=randint(1, 6)).id

    if lock:
        release_lock(lock_name)


@task
def ping_workers():
    """ Ping enabled worker and disable them if they doesn't respond a pong """
    from .models import Worker

    workers = Worker.objects.filter(enabled=True).only('pk', 'name')
    pings = [list(node)[0] for node in current_app.control.ping(timeout=3)]
    max_failure = settings.MAILSEND['MX_WORKER_MAX_PING_FAILURES']

    for worker in workers:
        log.debug('[{}] Pinging worker... (timeout=3)'.format(worker.ip))
        key = '{}:worker:ping_failures:{}'.format(
            settings.MAILSEND.get('CACHE_PREFIX'), worker.ip)
        if worker.name not in pings:
            failure_counter = conn.get(key)
            if failure_counter is None:
                conn.set(key, 0, 60 * 5)
                failure_counter = 0
            log.debug('[{}] No response (failure={},max={})'.format(
                worker.ip, failure_counter, max_failure))
            if failure_counter > max_failure:
                log.warn(
                    "[{}] Worker (pk:{}) seems to have crashed because it "
                    "doesn't have updated its status. Disabling it...".format(
                        worker.name, worker.pk))
                worker.enabled = False
                worker.save()
                conn.delete(key)
            else:
                log.debug(
                    "[{}] This is a soft warning, let's see "
                    "next ping...".format(worker.ip))
                conn.incr(key)
        else:
            log.debug('[{}] Worker is up'.format(worker.ip))
            conn.delete(key)


@task
def check_disabled_workers():
    """
    Check if disabled workers have tasks in queue, then re-route them
    """
    from .models import Worker
    from .tasks import route_envelope

    class Counter:
        pass
    c = current_app.connection()
    counter = Counter()
    counter.count = 0

    def process_message(body, message):
        identifier = body.get('args', [])[0]
        attempts = body.get('args')[1]
        log.info(
            '[{}] Republishing mail into routing task (attempts={})...'.format(
                identifier, attempts))
        route_envelope.apply_async(body.get('args'))
        message.ack()
        counter.count += 1

    for worker in Worker.objects.filter(enabled=False).only('ip'):
        queues = [
            worker.get_queue(connection),
            worker.get_queue(connection, retry=True)]
        for queue in queues:
            queue = worker.get_queue(connection)
            size = worker.get_queue_size(queue)
            if size:
                log.info(
                    "{} tasks remaining in disabled queue {}. Republishing them...".format(
                        size, queue.name))
                task_consumer = current_app.amqp.TaskConsumer(
                    c, queues=[queue], callbacks=[process_message])
                with task_consumer:
                    while counter.count <= size:
                        try:
                            connection.drain_events(timeout=2)
                        except socket.timeout:
                            return


@task
def dispatch_queued():
    """
    Reroute all queued tasks
    This task is not used for now but maybe a management command
    could be usefull.
    """
    from .tasks import route_envelope

    class Counter:
        pass
    connection = current_app.connection()
    counter = Counter()
    counter.count = 0

    def process_message(body, message):
        identifier = body.get('args', [])[0]
        attempts = body.get('args')[1]
        log.info(
            'Republishing {} mail into routing task (attempts={})...'.format(
                identifier, attempts))
        message.ack()
        route_envelope.apply_async(body.get('args'))
        counter.count += 1

    queue = get_queue(connection, settings.MAILSEND['QUEUED_MAIL_QUEUE'])
    size = get_queue_size(queue)
    if size:
        log.info("Rerouting {} tasks from {} queue...".format(
            size, settings.MAILSEND['QUEUED_MAIL_QUEUE']))
        task_consumer = current_app.amqp.TaskConsumer(
            connection, queues=[queue], callbacks=[process_message])
        with task_consumer:
            while counter.count <= size:
                try:
                    connection.drain_events(timeout=2)
                except socket.timeout:
                    return


def get_envelope_token(identifier):
    token = conn.get(
        '{}:token:{}'.format(settings.MAILSEND['CACHE_PREFIX'], identifier))
    if token:
        return token.decode('utf-8')


def set_envelope_token(identifier):
    token = str(uuid.uuid4())
    conn.set(
        '{}:token:{}'.format(settings.MAILSEND['CACHE_PREFIX'], identifier),
        token, settings.MAILSEND['TOKEN_CACHE_TIMEOUT'])
    return token


def delete_envelope_token(identifier):
    return conn.delete('{}:token:{}'.format(
        settings.MAILSEND['CACHE_PREFIX'], identifier))
