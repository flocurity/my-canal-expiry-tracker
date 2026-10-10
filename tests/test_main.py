import json
from unittest.mock import Mock

import pytest

from mycanal_expiry_tracker import cli as main


def test_invalid_input_prevents_api_and_output(tmp_path, monkeypatch):
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input' / 'bad.json').write_text('invalid')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    client = Mock()
    monkeypatch.setattr(main, 'CanalClient', client)
    assert main.main(['--from-cache']) == 1
    client.assert_not_called()
    assert not (tmp_path / 'output').exists()
    assert not (tmp_path / 'cache').exists()


def test_end_to_end_mocked(tmp_path, monkeypatch, fixture_data):
    (tmp_path / 'input').mkdir()
    playlist = fixture_data('playlist.json')
    playlist['contents'][1].update(seasonID='squirtle_s3', episodeID='squirtle_s3e3')
    (tmp_path / 'input' / 'page.json').write_text(json.dumps(playlist))
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    from mycanal_hodor_core.bootstrap import HodorRuntimeContext
    runtime = HodorRuntimeContext('a' * 32, 'FAKE_AUTH', '42')
    authentication = Mock(headers=runtime.headers, secrets=['FAKE_AUTH'])
    authentication.bootstrap.return_value = runtime
    monkeypatch.setattr(main, 'vault', lambda action: 'FAKE_PASS_ID')
    monkeypatch.setattr(main, 'PassIdAuth', Mock(return_value=authentication))
    monkeypatch.setattr(main, 'acquire_pages', Mock(return_value=[json.dumps(playlist).encode()]))
    monkeypatch.setattr(main, 'profile_path', lambda application: tmp_path / 'profile.json')
    client = Mock()
    client.fetch.side_effect = lambda url, content_id: fixture_data(
        'detail_movie.json' if content_id == 'fiction_50001' else 'detail_series_v5.json'
    )
    client.fetch_episodes.return_value = fixture_data('episodes_series.json')
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(main, 'CanalClient', Mock(return_value=context))
    assert main.main([]) == 0
    assert (tmp_path / 'output' / 'ma-liste-canal.xlsx').exists()
    assert (tmp_path / 'cache' / 'details.json').exists()
    assert client.fetch.call_count == 2
    assert client.fetch_episodes.call_count == 1
    assert main.main([]) == 0
    assert client.fetch.call_count == 4
    assert client.fetch_episodes.call_count == 2
    assert main.main(['--from-cache']) == 0
    assert client.fetch.call_count == 4
    # Publication intentionally refuses to overwrite an existing backup.
    for backup in (tmp_path / 'input').glob('*.bak'):
        backup.unlink()
    assert main.main(['--refresh', '--delay', '0.5']) == 0
    assert client.fetch.call_count == 6
    assert client.fetch_episodes.call_count == 3


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'bad'])
def test_bad_delay(value):
    with pytest.raises(SystemExit) as error:
        main.main(['--delay', value])
    assert error.value.code == 2


@pytest.mark.parametrize('flags', [
    ['--from-cache', '--curl'], ['--from-cache', '--refresh'], ['--getinfo'],
])
def test_incompatible_or_removed_options_do_not_authenticate(flags, monkeypatch):
    vault = Mock(side_effect=AssertionError('Authentication must not start'))
    monkeypatch.setattr(main, 'vault', vault)
    with pytest.raises(SystemExit) as error:
        main.main(flags)
    assert error.value.code == 2
    vault.assert_not_called()


def test_offline_partial_report_never_authenticates_or_opens_client(tmp_path, monkeypatch, fixture_data):
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input' / 'page.json').write_text(json.dumps(fixture_data('playlist.json')))
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    for name in ('vault', 'PassIdAuth', 'read_curl', 'CanalClient'):
        monkeypatch.setattr(main, name, Mock(side_effect=AssertionError('Offline violation')))
    writer = Mock()
    monkeypatch.setattr(main, 'write_excel', writer)
    assert main.main(['--from-cache']) == 0
    results = writer.call_args.args[0]
    assert len(results) == 2
    assert {result.status for result in results} == {'Données locales incomplètes'}
    assert not (tmp_path / 'cache').exists()


def test_failed_new_profile_acquisition_preserves_every_local_dataset(tmp_path, monkeypatch):
    from mycanal_hodor_core.bootstrap import HodorRuntimeContext
    from mycanal_expiry_tracker.canal_api import DetailError
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input' / 'old.json').write_bytes(b'{"contents":[]}')
    (tmp_path / 'input' / '.acquisition-profile').write_text('{"profileId":"old"}')
    (tmp_path / 'cache').mkdir()
    (tmp_path / 'cache' / 'details.json').write_bytes(b'old cache')
    authentication = Mock(secrets=['FAKE_PASS_ID'], headers={'tokenPass': 'NEW'})
    authentication.bootstrap.return_value = HodorRuntimeContext('a' * 32, 'NEW', 'new')
    monkeypatch.setattr(main, 'vault', lambda _: 'FAKE_PASS_ID')
    monkeypatch.setattr(main, 'PassIdAuth', Mock(return_value=authentication))
    monkeypatch.setattr(main, 'acquire_pages', Mock(side_effect=DetailError('HTTP 403')))
    client = Mock()
    client.return_value.__enter__ = Mock(return_value=Mock())
    client.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(main, 'CanalClient', client)
    before = {str(p.relative_to(tmp_path)): p.read_bytes()
              for p in tmp_path.rglob('*') if p.is_file()}
    assert main.main([], data_dir=tmp_path) == 1
    assert before == {str(p.relative_to(tmp_path)): p.read_bytes()
                      for p in tmp_path.rglob('*') if p.is_file()}


def test_auth_management_is_standalone(tmp_path, monkeypatch):
    vault = Mock()
    monkeypatch.setattr(main, 'vault', vault)
    monkeypatch.setattr(main, 'CanalClient', Mock(side_effect=AssertionError('No HTTP')))
    assert main.main(['--auth', 'set'], data_dir=tmp_path) == 0
    vault.assert_called_once_with('set')
    assert list(tmp_path.iterdir()) == []
