import json
from datetime import datetime, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from structlog.testing import capture_logs

from mycanal_expiry_tracker import cli as main
from mycanal_expiry_tracker.acquisition import (
    AcquisitionError, acquire_pages, parse_curl, publish_pages, read_curl,
)
from mycanal_expiry_tracker.canal_api import CanalClient, DetailError
from mycanal_expiry_tracker.playlist import load_playlist

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
        assert main.main(['--getinfo']) == 1
    factory.assert_not_called()
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}
    assert reason in str(logs)
    assert AUTH not in str(logs) and PROFILE not in str(logs) and TOKEN not in str(logs)


@pytest.mark.parametrize('page_count', [1, 2, 5])
def test_complete_acquisition_raw_files_and_loader(cli, page_count):
    directory, api, _ = cli
    (directory / 'history.json.bak').write_bytes(b'untouched')
    pages = [raw_page(n < page_count, f'opaque+/={n}') for n in range(1, page_count + 1)]
    api.fetch_playlist_page.side_effect = pages
    with capture_logs() as logs:
        assert main.main(['--getinfo']) == 0
    assert api.fetch_playlist_page.call_count == page_count
    for n, call in enumerate(api.fetch_playlist_page.call_args_list):
        query = parse_qs(urlsplit(call.args[0]).query)
        assert urlsplit(call.args[0]).path == f'/api/v2/mycanal/me/{TOKEN}/lists/playlist'
        assert query == dict(maxContentRemaining=['500'], get=['100'],
                             **({'after': [f'opaque+/={n}']} if n else {}))
        assert call.args[1] == {'tokenPass': AUTH, 'xx-profile-id': PROFILE}
    active = sorted(directory.glob('*.json'))
    assert [p.read_bytes() for p in active] == pages
    assert (directory / 'old.json.bak').read_bytes() == b'{"contents":[]}'
    assert (directory / 'history.json.bak').read_bytes() == b'untouched'
    assert load_playlist(directory) == []
    assert not (directory.parent / 'cache').exists()
    assert not (directory.parent / 'output').exists()
    assert all(secret not in str(logs) for secret in (AUTH, PROFILE, TOKEN))
    assert all(secret.encode() not in p.read_bytes() for secret in (AUTH, PROFILE, TOKEN)
               for p in active)


def test_timestamp_and_api_returned_url_tokens_are_preserved(tmp_path):
    body = json.dumps({'contents': [], 'paging': {'hasNextPage': False},
                       'url': URL}).encode()
    api = Mock()
    api.fetch_playlist_page.return_value = body
    pages = acquire_pages(parse_curl(CURL), api)
    paths = publish_pages(pages + [body], tmp_path,
                          datetime(2026, 10, 1, 16, 42, tzinfo=timezone.utc))
    assert [p.name for p in paths] == ['2026-10-01.18-42.json', '2026-10-01.18-42.page2.json']
    assert [p.read_bytes() for p in paths] == [body, body]


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
    assert main.main(['--getinfo']) == 1
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert api.fetch_playlist_page.call_count == len(responses)


@pytest.mark.parametrize('echo', [{'tokenPass': 'anything'}, {'xx-profile-id': 'anything'},
                                 {'nested': [AUTH]}, {'nested': [PROFILE]}])
def test_echoed_authentication_refused(cli, echo):
    directory, api, _ = cli
    payload = json.loads(raw_page())
    payload.update(echo)
    api.fetch_playlist_page.return_value = json.dumps(payload).encode()
    with capture_logs() as logs:
        assert main.main(['--getinfo']) == 1
    assert AUTH not in str(logs) and PROFILE not in str(logs)
    assert [p.name for p in directory.iterdir()] == ['old.json']


def test_backup_collision_preserves_both_files(cli):
    directory, api, _ = cli
    (directory / 'old.json.bak').write_bytes(b'history')
    api.fetch_playlist_page.return_value = raw_page()
    assert main.main(['--getinfo']) == 1
    assert (directory / 'old.json').read_bytes() == b'{"contents":[]}'
    assert (directory / 'old.json.bak').read_bytes() == b'history'
    assert len(list(directory.iterdir())) == 2


def test_publish_failure_rolls_back(tmp_path, monkeypatch):
    import mycanal_expiry_tracker.acquisition as acquisition
    (tmp_path / 'old.json').write_bytes(b'old')
    move = acquisition._move_without_overwrite

    def fail_second_page(source, destination):
        if destination.name.endswith('.page2.json'):
            raise OSError('synthetic failure')
        move(source, destination)

    monkeypatch.setattr(acquisition, '_move_without_overwrite', fail_second_page)
    with pytest.raises(AcquisitionError):
        publish_pages([raw_page(), raw_page()], tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {'old.json': b'old'}


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
