import json
from datetime import datetime, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from structlog.testing import capture_logs

from mycanal_expiry_tracker import cli as main
from mycanal_expiry_tracker.acquisition import (
    AcquisitionError, acquire_pages, parse_curl, read_curl,
)
from mycanal_expiry_tracker.canal_api import CanalClient, DetailError

TOKEN = 'a' * 32
AUTH = 'FAKE_AUTH_NOT_VALID'
PROFILE = 'FAKE_PROFILE_NOT_VALID'
URL = f'https://hodor.canalplus.pro/api/v2/mycanal/me/{TOKEN}/lists/playlist'
CURL = f"curl '{URL}' -H 'tokenPass: {AUTH}' -H 'xx-profile-id: {PROFILE}' --compressed"


def raw_page(more=False, cursor=None):
    # Whitespace, unicode escapes, and field order must survive byte-for-byte.
    return ('{ "contents" : [{"title": "Synthetic"}], "evidence": "\u00e9", "paging": '
            + json.dumps({'hasNextPage': more, 'idEnd': cursor}) + ' }\n').encode()


@pytest.fixture
def cli(tmp_path, monkeypatch):
    directory = tmp_path / 'input'
    directory.mkdir()
    (directory / 'old.json').write_bytes(b'{"contents":[]}')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    monkeypatch.setattr(main, 'read_curl', lambda: CURL)
    api = Mock()
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=api)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(main, 'CanalClient', factory)
    return directory, api, factory


@pytest.mark.parametrize('command, reason', [
    (CURL.replace('/lists/playlist', '/lists/other'), 'playlist URL'),
    (CURL.replace('/me/', '/page/'), 'playlist URL'),
    (f"curl '{URL}' -H 'xx-profile-id: {PROFILE}'", 'Missing tokenPass'),
])
def test_invalid_input_no_requests_or_files(cli, monkeypatch, command, reason):
    directory, api, factory = cli
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    monkeypatch.setattr(main, 'read_curl', lambda: command)
    with capture_logs() as logs:
        assert main.main(['--curl']) == 1
    factory.assert_not_called()
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert reason in str(logs)
    assert AUTH not in str(logs) and PROFILE not in str(logs) and TOKEN not in str(logs)


@pytest.mark.parametrize('responses', [
    [DetailError('HTTP 401')],
    [raw_page(True, 'one'), DetailError('HTTP 503')],
    [raw_page(True, 'one'), b'not json'],
    [raw_page(True, 'one'), b'{"contents": [], "paging": {}}'],
    [raw_page(True, None)],
    [raw_page(True, 'loop'), raw_page(True, 'loop')],
    [raw_page(True, str(n)) for n in range(5)],
    [b'{"contents": {}, "paging": {"hasNextPage": false}}'],
])
def test_failed_acquisition_preserves_old_export(cli, responses):
    directory, api, _ = cli
    api.fetch_playlist_page.side_effect = responses
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    assert main.main(['--curl']) == 1
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert api.fetch_playlist_page.call_count == len(responses)


@pytest.mark.parametrize('status', [401, 403])
def test_pass_id_acquisition_recovers_once_with_current_headers(status):
    context = parse_curl(CURL)
    authentication = Mock(headers=context.headers, secrets=[AUTH, PROFILE])

    def renew(**kwargs):
        authentication.headers = {'tokenPass': 'NEW_FAKE_TOKEN', 'xx-profile-id': PROFILE}
        authentication.secrets.append('NEW_FAKE_TOKEN')

    authentication.ensure.side_effect = renew
    client = Mock()
    client.fetch_playlist_page.side_effect = [DetailError('HTTP', status_code=status),
                                             raw_page(True, 'next'), raw_page()]
    assert len(acquire_pages(context, client, authentication)) == 2
    authentication.ensure.assert_called_once_with(force=True)
    assert client.fetch_playlist_page.call_args_list[1].args[1]['tokenPass'] == 'NEW_FAKE_TOKEN'
    assert client.fetch_playlist_page.call_args_list[2].args[1]['tokenPass'] == 'NEW_FAKE_TOKEN'
    assert context.token_pass == AUTH


def test_acquisition_recovery_budget_applies_to_entire_pagination():
    context = parse_curl(CURL)
    authentication = Mock(headers=context.headers, secrets=[AUTH])
    client = Mock()
    client.fetch_playlist_page.side_effect = [DetailError('HTTP', status_code=401),
                                             raw_page(True, 'next'),
                                             DetailError('HTTP', status_code=403)]
    with pytest.raises(DetailError):
        acquire_pages(context, client, authentication)
    authentication.ensure.assert_called_once_with(force=True)
    assert client.fetch_playlist_page.call_count == 3


def test_repeated_authentication_failure_is_not_retried_again():
    context = parse_curl(CURL)
    authentication = Mock(headers=context.headers, secrets=[AUTH])
    client = Mock()
    client.fetch_playlist_page.side_effect = [DetailError('HTTP', status_code=401)] * 2
    with pytest.raises(DetailError):
        acquire_pages(context, client, authentication)
    authentication.ensure.assert_called_once_with(force=True)
    assert client.fetch_playlist_page.call_count == 2


def test_shared_transport_retries_without_sensitive_logging(monkeypatch):
    monkeypatch.setattr('mycanal_hodor_core.http.time.sleep', lambda _: None)
    responses = [Mock(status_code=429, headers={'Retry-After': '0'}),
                 Mock(status_code=200, content=raw_page())]
    with CanalClient(delay=0) as api:
        get = Mock(side_effect=responses)
        monkeypatch.setattr(api.session, 'get', get)
        with capture_logs() as logs:
            assert acquire_pages(parse_curl(CURL), api) == [raw_page()]
        assert get.call_count == 2
        assert api.session.headers['Accept-Encoding'] == 'deflate, gzip'
        assert 'Firefox/' in api.session.headers['User-Agent']
        assert 'tokenPass' not in api.session.headers
        assert 'xx-profile-id' not in api.session.headers
        assert get.call_args.kwargs['allow_redirects'] is False
        assert all(secret not in str(logs) for secret in (AUTH, PROFILE, TOKEN))
        for response in responses:
            response.close.assert_called_once()
        get.side_effect = requests.RequestException(f'{AUTH} {PROFILE} {URL}')
        with pytest.raises(DetailError) as error:
            api.fetch_playlist_page(URL, {'tokenPass': AUTH, 'xx-profile-id': PROFILE})
        assert str(error.value) == 'RequestException'
        assert error.value.__suppress_context__


def test_browser_query_context_survives_pagination():
    from urllib.parse import parse_qsl, urlencode

    browser = [('dsp', 'contentGrid'), ('imageRatio', '169'), ('imageSize', 'medium'),
               ('titleDisplayMode', 'subtitle'), ('displayLogo', 'true'),
               ('discoverMode', 'false'), ('distmodes', 'svod,tvod'),
               ('featureToggles', 'detailLight'), ('extra', ''), ('extra', 'two'),
               ('get', '20'), ('get', '200'), ('maxContentRemaining', '5'),
               ('after', 'copied-cursor')]
    command = CURL.replace(URL, URL + '?' + urlencode(browser))
    context = parse_curl(command)
    assert context.query_parameters == tuple(browser)
    client = Mock()
    client.fetch_playlist_page.side_effect = [raw_page(True, 'opaque+/=server'), raw_page()]
    assert acquire_pages(context, client) == [raw_page(True, 'opaque+/=server'), raw_page()]
    preserved = browser[:-4]
    for index, call in enumerate(client.fetch_playlist_page.call_args_list):
        query = parse_qsl(urlsplit(call.args[0]).query, keep_blank_values=True)
        assert query == preserved + [('get', '100'), ('maxContentRemaining', '500')] + (
            [('after', 'opaque+/=server')] if index else []
        )


@pytest.mark.parametrize('path', [f'/api/v2/mycanal/page/{TOKEN}/103412.json',
                                  f'/api/v2/mycanal/me/{TOKEN}/profile'])
def test_playlist_transport_rejects_other_resources(monkeypatch, path):
    with CanalClient() as client:
        get = Mock()
        monkeypatch.setattr(client.session, 'get', get)
        with pytest.raises(DetailError):
            client.fetch_playlist_page('https://hodor.canalplus.pro' + path,
                                       {'tokenPass': AUTH, 'xx-profile-id': PROFILE})
        get.assert_not_called()


def test_pass_id_navigation_tokens_are_transient_not_rejected(tmp_path, fixture_data):
    from mycanal_expiry_tracker.playlist import parse_playlist
    from mycanal_expiry_tracker.cache import save_snapshot
    from mycanal_expiry_tracker.report import to_report_rows
    from mycanal_expiry_tracker.tracker import process_items

    context = parse_curl(CURL)
    authentication = Mock(headers=context.headers,
                          secrets=['FAKE_PASS_ID', AUTH, PROFILE, TOKEN])
    payload = fixture_data('playlist.json')
    payload['contents'] = payload['contents'][:1]
    payload['contents'][0]['onClick']['URLPage'] = (
        f'https://hodor.canalplus.pro/api/v2/mycanal/detail/{TOKEN}/okapi/'
        'fiction_50001.json?detailType=detailPage&objectType=unit')
    payload['paging'] = {'hasNextPage': False}
    payload['tokenPass'] = AUTH  # Discarded HTTP metadata is not persisted.
    client = Mock(authentication=authentication)
    client.fetch_playlist_page.return_value = json.dumps(payload).encode()
    client.fetch.return_value = fixture_data('detail_movie.json')
    pages = acquire_pages(context, client, authentication)
    items = parse_playlist(pages)
    rows = to_report_rows(process_items(items, client))
    path = save_snapshot(rows, tmp_path, secrets=tuple(authentication.secrets))
    assert all(secret not in path.read_text() for secret in (AUTH, PROFILE, TOKEN, 'FAKE_PASS_ID'))
    assert len(list(tmp_path.iterdir())) == 1
