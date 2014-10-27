# -*- coding: utf-8 -*-
import logging
from datetime import datetime

from pyramid.events import subscriber
from pyramid.security import Everyone, principals_allowed_by_permission
from pyramid.renderers import render
from hem.db import get_session
from horus.events import NewRegistrationEvent


from h.notification.notifier import send_email, TemplateRenderException
from h.notification import types
from h.notification.models import Subscriptions
from h.notification.gateway import user_name, user_profile_url, standalone_url, get_user_by_name
from h.events import LoginEvent, AnnotationEvent
from h import interfaces

log = logging.getLogger(__name__)  # pylint: disable=invalid-name


def parent_values(annotation, request):
    if 'references' in annotation:
        registry = request.registry
        store = registry.queryUtility(interfaces.IStoreClass)(request)
        parent = store.read(annotation['references'][-1])
        if 'references' in parent:
            grandparent = store.read(parent['references'][-1])
            parent['quote'] = grandparent['text']

        return parent
    else:
        return {}


def create_template_map(request, reply, data):
    document_title = ''
    if 'document' in reply:
        document_title = reply['document'].get('title', '')

    parent_user = user_name(data['parent']['user'])
    reply_user = user_name(reply['user'])

    # Currently we cut the UTC format because time.strptime has problems
    # parsing it, and of course it'd only correct the backend's timezone
    # which is not meaningful for international users
    date_format = '%Y-%m-%dT%H:%M:%S.%f'
    parent_timestamp = datetime.strptime(data['parent']['created'][:-6], date_format)
    reply_timestamp = datetime.strptime(reply['created'][:-6], date_format)

    seq = ('http://', str(request.domain), '/app?__formid__=unsubscribe&subscription_id=', str(data['subscription']['id']))
    unsubscribe = "".join(seq)

    return {
        'document_title': document_title,
        'document_path': data['parent']['uri'],
        'parent_text': data['parent']['text'],
        'parent_user': parent_user,
        'parent_timestamp': parent_timestamp,
        'parent_user_profile': user_profile_url(
            request, data['parent']['user']),
        'parent_path': standalone_url(request, data['parent']['id']),
        'reply_text': reply['text'],
        'reply_user': reply_user,
        'reply_timestamp': reply_timestamp,
        'reply_user_profile': user_profile_url(request, reply['user']),
        'reply_path': standalone_url(request, reply['id']),
        'unsubscribe': unsubscribe
    }


def get_recipients(request, data):
    username = user_name(data['parent']['user'])
    user_obj = get_user_by_name(request, username)
    if not user_obj:
        log.warn("User not found! " + str(username))
        raise TemplateRenderException('User not found')
    return [user_obj.email]


def check_conditions(annotation, data):
    # Get the e-mail of the owner
    if 'user' not in data['parent'] or not data['parent']['user']:
        return False
    # Do not notify users about their own replies
    if annotation['user'] == data['parent']['user']:
        return False

    # Is he the proper user?
    if data['parent']['user'] != data['subscription']['uri']:
        return False

    # Else okay
    return True


# Create a reply template for a uri
def create_subscription(request, uri, active):
    session = get_session(request)
    subs = Subscriptions(
        uri=uri,
        template=types.REPLY_TEMPLATE,
        description='General reply notification',
        active=active
    )

    session.add(subs)
    session.flush()


@subscriber(AnnotationEvent)
def send_notifications(event):
    # Extract data
    action = event.action
    request = event.request
    annotation = event.annotation

    # And for them we need only the creation action
    if action != 'create':
        return

    # Check for authorization. Send notification only for public annotation
    # XXX: This will be changed and fine grained when
    # user groups will be introduced
    if Everyone not in principals_allowed_by_permission(annotation, 'read'):
        return

    # Store the parent values as additional data
    data = {
        'parent': parent_values(annotation, request)
    }

    subscriptions = Subscriptions.get_active_subscriptions_for_a_template(request, types.REPLY_TEMPLATE)
    for subscription in subscriptions:
        data['subscription'] = {
            'id': subscription.id,
            'uri': subscription.uri,
            'parameters': subscription.parameters,
            'query': subscription.query
        }

        # Validate annotation
        if check_conditions(annotation, data):
            try:
                # Render e-mail parts
                tmap = create_template_map(request, annotation, data)
                text = render('h:notification/templates/reply_notification.txt', tmap, request)
                html = render('h:notification/templates/reply_notification.pt', tmap, request)
                subject = render('h:notification/templates/reply_notification_subject.txt', tmap, request)
                recipients = get_recipients(request, data)
                send_email(request, subject, text, html, recipients)
            # ToDo: proper exception handling here
            except TemplateRenderException:
                log.exception('Failed to render subscription template %s', subscription)
            except:
                log.exception('Unknown error when trying to render subscription template %s', subscription)


@subscriber(NewRegistrationEvent)
def registration_subscriptions(event):
    request = event.request
    user_uri = 'acct:{}@{}'.format(event.user.username, request.domain)
    create_subscription(event.request, user_uri, True)
    event.user.subscriptions = True


# For backwards compatibility, generate reply notification if not exists
@subscriber(LoginEvent)
def check_reply_subscriptions(event):
    request = event.request
    user_uri = 'acct:{}@{}'.format(event.user.username, request.domain)
    res = Subscriptions.get_a_template_for_uri(request, user_uri, types.REPLY_TEMPLATE)
    if not len(res):
        create_subscription(event.request, user_uri, True)
        event.user.subscriptions = True


def includeme(config):
    config.scan(__name__)
