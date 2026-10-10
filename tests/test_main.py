import json
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from structlog.testing import capture_logs

from mycanal_expiry_tracker import cli
from mycanal_expiry_tracker.cache import load_snapshot, save_snapshot
from mycanal_expiry_tracker.canal_api import DetailError
from mycanal_expiry_tracker.report import to_report_rows
from mycanal_expiry_tracker.tracker import ContentResult
from mycanal_hodor_core.bootstrap import HodorRuntimeContext


@pytest.fixture
def runtime(tmp_path, monkeypatch, fixture_data):
    playlist = fixture_data('playlist.json')
    playlist['contents'][1].update(seasonID='squirtle_s3', episodeID='squirtle_s3e3')
    # Realistic navigation token must stay transient, unlike report metadata.
    playlist['contents'][0]['onClick']['URLPage'] = playlist['contents'][0]['onClick']['URLPage'].replace('/fiction/', '/' + 'a' * 32 + '/')
    context = HodorRuntimeContext('a' * 32, 'FAKE_AUTH', '42')
    authentication = Mock(headers=context.headers, secrets=['FAKE_PASS_ID', 'FAKE_AUTH', 'a' * 32])
    authentication.bootstrap.return_value = context
    monkeypatch.setattr(cli, 'vault', Mock(return_value='FAKE_PASS_ID'))
    monkeypatch.setattr(cli, 'PassIdAuth', Mock(return_value=authentication))
    monkeypatch.setattr(cli, 'profile_path', lambda _: tmp_path / 'preference.json')
    monkeypatch.setattr(cli, 'acquire_pages', Mock(return_value=[json.dumps(playlist).encode()]))
    client = Mock()
    client.fetch.side_effect = lambda url, content_id: fixture_data(
        'detail_movie.json' if content_id == 'fiction_50001' else 'detail_series_v5.json')
    client.fetch_episodes.return_value = fixture_data('episodes_series.json')
    manager = Mock()
    manager.__enter__ = Mock(return_value=client)
    manager.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(cli, 'CanalClient', Mock(return_value=manager))
    return client, authentication


@pytest.mark.parametrize('profile_id', ['0', '42'])
@pytest.mark.parametrize('curl', [False, True])
def test_profile_is_context_not_a_diagnostic_or_persistence_secret(
        tmp_path, runtime, monkeypatch, profile_id, curl):
    _, authentication = runtime
    context = HodorRuntimeContext('a' * 32, 'FAKE_AUTH', profile_id)
    authentication.headers = context.headers
    authentication.bootstrap.return_value = context
    monkeypatch.setattr(cli, 'read_curl', lambda: 'synthetic curl')
    monkeypatch.setattr(cli, 'parse_curl', lambda _: context)
    payload = json.loads(cli.acquire_pages.return_value[0])
    title = 'Film 2000, 1942, 2042-10-10, HTTP 200/429'
    payload['contents'][0].update(title=title, contentID='42_50001')
    cli.acquire_pages.return_value = [json.dumps(payload).encode()]
    process = Mock(wraps=cli.process_items)
    save = Mock(wraps=cli.save_snapshot)
    monkeypatch.setattr(cli, 'process_items', process)
    monkeypatch.setattr(cli, 'save_snapshot', save)
    with capture_logs() as logs:
        assert cli.main(['--curl'] if curl else [], data_dir=tmp_path) == 0
    assert profile_id not in process.call_args.kwargs['secrets']
    assert profile_id not in save.call_args.kwargs['secrets']
    assert 'FAKE_AUTH' in save.call_args.kwargs['secrets']
    assert load_snapshot(tmp_path / 'cache')[0].title == title
    assert title in str(logs)
    assert cli.acquire_pages.call_args.args[0].profile_id == profile_id


def test_credential_equal_to_profile_id_is_still_protected(tmp_path, runtime, monkeypatch):
    _, authentication = runtime
    context = HodorRuntimeContext('a' * 32, 'FAKE_AUTH', '0')
    authentication.headers = context.headers
    authentication.secrets = ['0', 'FAKE_AUTH', 'a' * 32]
    authentication.bootstrap.return_value = context
    monkeypatch.setattr(cli, 'vault', lambda _: '0')
    payload = json.loads(cli.acquire_pages.return_value[0])
    payload['contents'][0]['title'] = 'Film 2000'
    cli.acquire_pages.return_value = [json.dumps(payload).encode()]
    assert cli.main([], data_dir=tmp_path) == 1
    assert not (tmp_path / 'cache').exists()


def test_normal_never_reads_old_cache_or_input_and_refetches(tmp_path, runtime, monkeypatch):
    client, _ = runtime
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input' / 'bad.json').write_text('invalid input')
    (tmp_path / 'cache').mkdir()
    (tmp_path / 'cache' / 'details.json').write_text('invalid legacy')
    (tmp_path / 'cache' / '2000-01-01.00-00.cache.json').write_text('invalid old snapshot')
    monkeypatch.setattr(cli, 'load_snapshot', Mock(side_effect=AssertionError('Old cache read')))
    save = cli.save_snapshot
    stamps = iter([datetime(2026, 10, 2, 13, 31, tzinfo=timezone.utc),
                   datetime(2026, 10, 2, 13, 32, tzinfo=timezone.utc)])
    monkeypatch.setattr(cli, 'save_snapshot', lambda *a, **kw: save(*a, **kw, created_at=next(stamps)))
    assert cli.main([], data_dir=tmp_path) == 0
    assert cli.main([], data_dir=tmp_path) == 0
    assert client.fetch.call_count == 4
    assert client.fetch_episodes.call_count == 2
    assert (tmp_path / 'input' / 'bad.json').read_text() == 'invalid input'
    assert (tmp_path / 'cache' / 'details.json').read_text() == 'invalid legacy'
    assert len(list((tmp_path / 'cache').glob('*.cache.json'))) == 1
    assert len(list((tmp_path / 'cache').glob('*.bak'))) == 2


def test_normal_and_offline_have_identical_workbook_data_without_input(tmp_path, runtime, monkeypatch):
    assert cli.main([], data_dir=tmp_path) == 0
    assert not (tmp_path / 'input').exists()
    output = tmp_path / 'output' / 'ma-liste-canal.xlsx'
    with ZipFile(output) as book:
        before = {name: book.read(name) for name in book.namelist() if name.startswith('xl/')}
        assert all(b'a' * 32 not in data and b'FAKE_AUTH' not in data for data in before.values())
    snapshot_bytes = {p.name: p.read_bytes() for p in (tmp_path / 'cache').iterdir()}
    for name in ('vault', 'PassIdAuth', 'profile_path', 'CanalClient', 'process_items', 'acquire_pages', 'save_snapshot'):
        monkeypatch.setattr(cli, name, Mock(side_effect=AssertionError('Offline violation')))
    assert cli.main(['--from-cache'], data_dir=tmp_path) == 0
    with ZipFile(output) as book:
        assert before == {name: book.read(name) for name in book.namelist() if name.startswith('xl/')}
    assert snapshot_bytes == {p.name: p.read_bytes() for p in (tmp_path / 'cache').iterdir()}


def test_partial_enrichment_is_saved_and_regenerated(tmp_path, runtime, monkeypatch):
    client, _ = runtime
    client.fetch.side_effect = DetailError('HTTP 503')
    assert cli.main([], data_dir=tmp_path) == 0
    rows = load_snapshot(tmp_path / 'cache')
    assert len(rows) == 2
    assert {row.status for row in rows} == {'Erreur HTTP'}
    assert all(row.expiration is None for row in rows)
    monkeypatch.setattr(cli, 'CanalClient', Mock(side_effect=AssertionError('Network')))
    assert cli.main(['--from-cache'], data_dir=tmp_path) == 0


@pytest.mark.parametrize('flags', [['--refresh'], ['--from-cache', '--refresh'], ['--getinfo'],
                                   ['--from-cache', '--curl'], ['--auth', 'set', '--curl'],
                                   ['--from-cache', '--delay', '0'], ['--auth', 'set', '--delay', '0']])
def test_removed_or_incompatible_options_fail_before_auth(flags, monkeypatch):
    vault = Mock(side_effect=AssertionError('Auth'))
    monkeypatch.setattr(cli, 'vault', vault)
    with pytest.raises(SystemExit) as error:
        cli.main(flags)
    assert error.value.code == 2
    vault.assert_not_called()


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'bad'])
def test_invalid_delay(value):
    with pytest.raises(SystemExit):
        cli.main(['--delay', value])


def test_offline_without_snapshot_fails_without_auth(tmp_path, monkeypatch):
    for name in ('vault', 'PassIdAuth', 'CanalClient'):
        monkeypatch.setattr(cli, name, Mock(side_effect=AssertionError('Offline')))
    assert cli.main(['--from-cache'], data_dir=tmp_path) == 1
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('failure', [DetailError('HTTP 403'), KeyboardInterrupt()])
def test_acquisition_failure_preserves_previous_snapshot(tmp_path, runtime, monkeypatch, item, failure):
    previous = save_snapshot(to_report_rows([ContentResult(item, None, 'Date inconnue')]),
                             tmp_path / 'cache')
    original = previous.read_bytes()
    monkeypatch.setattr(cli, 'acquire_pages', Mock(side_effect=failure))
    assert cli.main([], data_dir=tmp_path) == 1
    assert previous.read_bytes() == original
    assert not list((tmp_path / 'cache').glob('*.bak'))


def test_interrupted_enrichment_does_not_publish(tmp_path, runtime):
    client, _ = runtime
    client.fetch.side_effect = KeyboardInterrupt()
    assert cli.main([], data_dir=tmp_path) == 1
    assert not (tmp_path / 'cache').exists()


def test_excel_failure_leaves_regenerable_snapshot(tmp_path, runtime, monkeypatch):
    monkeypatch.setattr(cli, 'write_excel', Mock(side_effect=OSError('failed')))
    assert cli.main([], data_dir=tmp_path) == 1
    assert len(load_snapshot(tmp_path / 'cache')) == 2


def test_real_xlsxwriter_file_creation_error_is_handled(tmp_path, runtime, monkeypatch):
    import xlsxwriter.workbook

    destination = tmp_path / 'output' / 'ma-liste-canal.xlsx'
    destination.parent.mkdir()
    destination.write_bytes(b'previous workbook')
    monkeypatch.setattr(xlsxwriter.workbook, 'ZipFile',
                        Mock(side_effect=PermissionError('synthetic write denied')))
    with capture_logs() as logs:
        assert cli.main([], data_dir=tmp_path) == 1
    assert destination.read_bytes() == b'previous workbook'
    assert list(destination.parent.iterdir()) == [destination]
    assert len(load_snapshot(tmp_path / 'cache')) == 2
    assert any(entry['event'] == 'execution_failed' for entry in logs)
    assert any(entry.get('exception_type') == 'FileCreateError' for entry in logs)


def test_credentials_in_selected_business_data_refuse_all_publication(tmp_path, runtime, monkeypatch):
    pages = json.loads(cli.acquire_pages.return_value[0])
    pages['contents'][0]['title'] = 'FAKE_PASS_ID'
    cli.acquire_pages.return_value = [json.dumps(pages).encode()]
    with capture_logs() as logs:
        assert cli.main([], data_dir=tmp_path) == 1
    assert 'FAKE_PASS_ID' not in str(logs)
    assert not (tmp_path / 'cache').exists()
    assert not (tmp_path / 'output').exists()


def test_curl_uses_same_fresh_pipeline_without_keyring(tmp_path, runtime, monkeypatch):
    monkeypatch.setattr(cli, 'vault', Mock(side_effect=AssertionError('Keyring')))
    monkeypatch.setattr(cli, 'PassIdAuth', Mock(side_effect=AssertionError('PassId')))
    monkeypatch.setattr(cli, 'read_curl', lambda: 'synthetic curl')
    monkeypatch.setattr(cli, 'parse_curl', lambda _: HodorRuntimeContext('a' * 32, 'FAKE_AUTH', '42'))
    assert cli.main(['--curl', '--delay', '0'], data_dir=tmp_path) == 0
    assert cli.CanalClient.call_args.kwargs['diagnostic_secrets'] == ('a' * 32, 'FAKE_AUTH')
    assert len(load_snapshot(tmp_path / 'cache')) == 2


def test_auth_management_only_changes_keyring(tmp_path, monkeypatch):
    vault = Mock()
    monkeypatch.setattr(cli, 'vault', vault)
    monkeypatch.setattr(cli, 'CanalClient', Mock(side_effect=AssertionError('HTTP')))
    assert cli.main(['--auth', 'set'], data_dir=tmp_path) == 0
    vault.assert_called_once_with('set')
    assert list(tmp_path.iterdir()) == []


def test_old_snapshot_content_is_never_opened(tmp_path, runtime, monkeypatch):
    from pathlib import Path
    directory = tmp_path / 'cache'
    directory.mkdir()
    old = directory / '2000-01-01.00-00.cache.json'
    old.write_text('unreadable legacy data')
    original_read = Path.read_text

    def checked_read(path, *args, **kwargs):
        if path == old:
            raise AssertionError('Normal execution read an old snapshot')
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'read_text', checked_read)
    assert cli.main([], data_dir=tmp_path) == 0
    assert old.with_name(old.name + '.bak').exists()


def test_snapshot_publication_failure_prevents_excel(tmp_path, runtime, monkeypatch):
    monkeypatch.setattr(cli, 'save_snapshot', Mock(side_effect=OSError('disk full')))
    writer = Mock()
    monkeypatch.setattr(cli, 'write_excel', writer)
    assert cli.main([], data_dir=tmp_path) == 1
    writer.assert_not_called()
    assert not (tmp_path / 'output').exists()
