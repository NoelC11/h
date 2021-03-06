# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import mock
import pytest

from pyramid.httpexceptions import HTTPNoContent, HTTPBadRequest

from h.views import api_groups as views
from h.services.list_groups import ListGroupsService
from h.services.group import GroupService
from h.services.group_links import GroupLinksService

pytestmark = pytest.mark.usefixtures('GroupsJSONPresenter')


@pytest.mark.usefixtures('list_groups_service', 'group_links_service')
class TestGroupsWithScope(object):

    def test_proxies_to_list_service(self, anonymous_request, list_groups_service):
        views.groups(anonymous_request)

        list_groups_service.request_groups.assert_called_once_with(
            user=None,
            authority=anonymous_request.authority,
            document_uri=None
        )

    def test_proxies_request_params(self, anonymous_request, list_groups_service):
        anonymous_request.params['document_uri'] = 'http://example.com/thisthing.html'
        anonymous_request.params['authority'] = 'foo.com'
        views.groups(anonymous_request)

        list_groups_service.request_groups.assert_called_once_with(
            user=None,
            authority='foo.com',
            document_uri='http://example.com/thisthing.html'
        )

    def test_overrides_authority_with_user_authority(self, authenticated_request, list_groups_service):
        authenticated_request.params['authority'] = 'foo.com'

        views.groups(authenticated_request)

        list_groups_service.request_groups.assert_called_once_with(
            user=authenticated_request.user,
            authority=authenticated_request.user.authority,
            document_uri=None
        )

    @pytest.fixture
    def anonymous_request(self, pyramid_request):
        pyramid_request.user = None
        return pyramid_request

    @pytest.fixture
    def authenticated_request(self, pyramid_request, factories):
        pyramid_request.user = factories.User()
        return pyramid_request


@pytest.mark.usefixtures('scope_feature_off', 'list_groups_service', 'group_links_service')
class TestGroups(object):

    def test_proxies_to_service(self, anonymous_request, list_groups_service):
        views.groups(anonymous_request)

        list_groups_service.all_groups.assert_called_once_with(
            user=None,
            authority=None,
            document_uri=None
        )

    def test_proxies_authority_param(self, anonymous_request, list_groups_service):
        anonymous_request.params['authority'] = 'foo.com'
        views.groups(anonymous_request)

        list_groups_service.all_groups.assert_called_once_with(
            user=None,
            authority='foo.com',
            document_uri=None
        )

    def test_proxies_document_uri_param(self, anonymous_request, list_groups_service):
        anonymous_request.params['document_uri'] = 'http://example.com/thisthing.html'
        views.groups(anonymous_request)

        list_groups_service.all_groups.assert_called_once_with(
            user=None,
            authority=None,
            document_uri='http://example.com/thisthing.html'
        )

    def test_uses_presenter_for_formatting(self, group_links_service, open_groups, list_groups_service, GroupsJSONPresenter, anonymous_request):  # noqa: N803
        list_groups_service.all_groups.return_value = open_groups

        views.groups(anonymous_request)

        GroupsJSONPresenter.assert_called_once_with(open_groups, group_links_service)

    def test_returns_dicts_from_presenter(self, anonymous_request, open_groups, list_groups_service, GroupsJSONPresenter):  # noqa: N803
        list_groups_service.all_groups.return_value = open_groups

        result = views.groups(anonymous_request)

        assert result == GroupsJSONPresenter(open_groups, anonymous_request).asdicts.return_value

    @pytest.fixture
    def open_groups(self, factories):
        return [factories.OpenGroup(), factories.OpenGroup()]

    @pytest.fixture
    def anonymous_request(self, pyramid_request):
        pyramid_request.user = None
        return pyramid_request


@pytest.mark.usefixtures('authenticated_userid', 'group_service')
class TestRemoveMember(object):

    def test_it_removes_current_user(self, shorthand_request, authenticated_userid, group_service):
        group = mock.sentinel.group

        views.remove_member(group, shorthand_request)

        group_service.member_leave.assert_called_once_with(group, authenticated_userid)

    def test_it_returns_no_content(self, shorthand_request):
        group = mock.sentinel.group

        response = views.remove_member(group, shorthand_request)

        assert isinstance(response, HTTPNoContent)

    def test_it_fails_with_username(self, username_request):
        group = mock.sentinel.group

        with pytest.raises(HTTPBadRequest):
            views.remove_member(group, username_request)

    @pytest.fixture
    def shorthand_request(self, pyramid_request):
        pyramid_request.matchdict['user'] = 'me'
        return pyramid_request

    @pytest.fixture
    def username_request(self, pyramid_request):
        pyramid_request.matchdict['user'] = 'bob'
        return pyramid_request

    @pytest.fixture
    def group_service(self, pyramid_config):
        service = mock.create_autospec(GroupService, spec_set=True, instance=True)
        pyramid_config.register_service(service, name='group')
        return service

    @pytest.fixture
    def authenticated_userid(self, pyramid_config):
        userid = 'acct:bob@example.org'
        pyramid_config.testing_securitypolicy(userid)
        return userid


@pytest.fixture
def GroupsJSONPresenter(patch):  # noqa: N802
    return patch('h.views.api_groups.GroupsJSONPresenter')


@pytest.fixture
def scope_feature_off(pyramid_request):
    pyramid_request.feature.flags['filter_groups_by_scope'] = False


@pytest.fixture
def group_links_service(pyramid_config):
    svc = mock.create_autospec(GroupLinksService, spec_set=True, instance=True)
    pyramid_config.register_service(svc, name='group_links')
    return svc


@pytest.fixture
def list_groups_service(pyramid_config):
    svc = mock.create_autospec(ListGroupsService, spec_set=True, instance=True)
    pyramid_config.register_service(svc, name='list_groups')
    return svc
