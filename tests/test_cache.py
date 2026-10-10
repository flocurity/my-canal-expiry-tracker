from dataclasses import replace
from datetime import date, datetime, timezone
import json
from unittest.mock import Mock

import pandas as pd
import pytest

from mycanal_expiry_tracker import cache
from mycanal_expiry_tracker.cache import load_snapshot, save_snapshot
from mycanal_expiry_tracker.excel import build_dataframe, write_excel
from mycanal_expiry_tracker.report import to_report_rows
from mycanal_expiry_tracker.tracker import ContentResult


@pytest.fixture
def rows(item):
    return to_report_rows([
        ContentResult(replace(item, duration_ms=5880000), date(2026, 11, 2), 'OK',
                      subgenre='Film Science-fiction', availability_text='lundi 2 novembre 23h59'),
        ContentResult(replace(item, content_id='failed'), None, 'Erreur HTTP'),
        ContentResult(replace(item, content_type='folder'), date(2026, 9, 30), 'OK',
                      duration_minutes=84, resume_episode='Mammouth', episodes_remaining=4,
                      season_numbers=(0, 3), availability_end_date=1790805540000),
    ])


def stamp(minute):
    return datetime(2026, 10, 2, 13, minute, tzinfo=timezone.utc)


def test_snapshot_alone_reproduces_partial_report(tmp_path, rows):
    path = save_snapshot(rows, tmp_path, created_at=stamp(32))
    assert path.name == '2026-10-02.15-32.cache.json'
    restored = load_snapshot(tmp_path)
    assert restored == rows
    assert restored[1].status == 'Erreur HTTP'
    assert restored[0].duration_minutes == 98
    pd.testing.assert_frame_equal(build_dataframe(rows, date(2026, 10, 2)),
                                  build_dataframe(restored, date(2026, 10, 2)))
    data = json.loads(path.read_text())
    assert set(data) == {'schema_version', 'rows'}
    for forbidden in ('detail_url', 'catalog', 'onClick', 'resume_fallback', 'user_progress'):
        assert forbidden not in path.read_text()


def test_archive_all_actives_and_select_latest_without_reading_backups(tmp_path, rows):
    first = save_snapshot(rows, tmp_path, created_at=stamp(31))
    original = first.read_bytes()
    second = save_snapshot([], tmp_path, created_at=stamp(32))
    assert not first.exists()
    assert first.with_name(first.name + '.bak').read_bytes() == original
    assert load_snapshot(tmp_path) == []
    # A manually left older active is ignored; backups may contain invalid data.
    first.write_text('invalid older file')
    first.with_name(first.name + '.bak').write_text('invalid backup')
    assert load_snapshot(tmp_path) == []
    second.write_text('invalid latest file')
    with pytest.raises(ValueError, match='Invalid latest'):
        load_snapshot(tmp_path)


def test_no_active_does_not_use_legacy_or_backup(tmp_path):
    (tmp_path / 'details.json').write_text('{}')
    (tmp_path / '2026-10-02.15-32.cache.json.bak').write_text('{}')
    with pytest.raises(ValueError, match='No active'):
        load_snapshot(tmp_path)


@pytest.mark.parametrize('collision', ['active', 'backup'])
def test_collisions_never_overwrite(tmp_path, rows, collision):
    path = save_snapshot(rows, tmp_path, created_at=stamp(31))
    if collision == 'backup':
        path.with_name(path.name + '.bak').write_bytes(b'history')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='collision'):
        save_snapshot([], tmp_path, created_at=stamp(31 if collision == 'active' else 32))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


@pytest.mark.parametrize('failure', [OSError('failed'), KeyboardInterrupt()])
def test_publication_rolls_back_on_failure_or_interrupt(tmp_path, rows, monkeypatch, failure):
    old = save_snapshot(rows, tmp_path, created_at=stamp(31))
    original = old.read_bytes()
    move = cache._move_without_overwrite

    def fail_publication(source, destination):
        if destination.name == '2026-10-02.15-32.cache.json':
            raise failure
        move(source, destination)

    monkeypatch.setattr(cache, '_move_without_overwrite', fail_publication)
    with pytest.raises(type(failure)):
        save_snapshot([], tmp_path, created_at=stamp(32))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {old.name: original}


def test_stage_failure_preserves_active(tmp_path, rows, monkeypatch):
    old = save_snapshot(rows, tmp_path, created_at=stamp(31))
    original = old.read_bytes()
    monkeypatch.setattr(cache.json, 'dumps', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        save_snapshot([], tmp_path, created_at=stamp(32))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {old.name: original}


def test_interrupt_immediately_after_archival_restores_active(tmp_path, rows, monkeypatch):
    old = save_snapshot(rows, tmp_path, created_at=stamp(31))
    original = old.read_bytes()
    move = cache._move_without_overwrite

    def interrupt_after_archive(source, destination):
        move(source, destination)
        if destination.name.endswith('.bak'):
            raise KeyboardInterrupt()

    monkeypatch.setattr(cache, '_move_without_overwrite', interrupt_after_archive)
    with pytest.raises(KeyboardInterrupt):
        save_snapshot([], tmp_path, created_at=stamp(32))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {old.name: original}


@pytest.mark.parametrize('phase', ['archive', 'publish'])
def test_interrupt_immediately_after_link_preserves_active(tmp_path, rows, monkeypatch, phase):
    old = save_snapshot(rows, tmp_path, created_at=stamp(31))
    original = old.read_bytes()
    link = cache.os.link

    def interrupt_after_link(source, destination):
        link(source, destination)
        if (phase == 'archive' and destination.name.endswith('.bak')
                or phase == 'publish' and destination.name == '2026-10-02.15-32.cache.json'):
            raise KeyboardInterrupt()

    monkeypatch.setattr(cache.os, 'link', interrupt_after_link)
    with pytest.raises(KeyboardInterrupt):
        save_snapshot([], tmp_path, created_at=stamp(32))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {old.name: original}


def test_move_collision_preserves_both_files(tmp_path):
    source = tmp_path / 'source'
    destination = tmp_path / 'destination'
    source.write_bytes(b'active')
    destination.write_bytes(b'history')
    with pytest.raises(FileExistsError):
        cache._move_without_overwrite(source, destination)
    assert source.read_bytes() == b'active'
    assert destination.read_bytes() == b'history'


def test_interrupt_after_archive_source_unlink_restores_active(tmp_path, rows, monkeypatch):
    old = save_snapshot(rows, tmp_path, created_at=stamp(31))
    original = old.read_bytes()
    unlink = cache.Path.unlink
    interrupted = False

    def interrupt_after_unlink(path, *args, **kwargs):
        nonlocal interrupted
        unlink(path, *args, **kwargs)
        if path == old and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(cache.Path, 'unlink', interrupt_after_unlink)
    with pytest.raises(KeyboardInterrupt):
        save_snapshot([], tmp_path, created_at=stamp(32))
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {old.name: original}


@pytest.mark.parametrize('field', ['title', 'service', 'category', 'subgenre', 'resume_episode', 'status', 'content_id'])
@pytest.mark.parametrize('secret', ['FAKE_PASS_ID', 'FAKE_TOKEN_PASS', 'RETIRED_TOKEN', 'a' * 32])
def test_secrets_refused_in_snapshot_and_excel(tmp_path, rows, field, secret):
    unsafe = [replace(rows[0], **{field: 'prefix ' + secret + ' suffix'})]
    secrets = ('FAKE_PASS_ID', 'FAKE_TOKEN_PASS', 'RETIRED_TOKEN')
    with pytest.raises(ValueError, match='Authentication'):
        save_snapshot(unsafe, tmp_path / 'cache', secrets=secrets)
    with pytest.raises(ValueError, match='Authentication'):
        write_excel(unsafe, tmp_path / 'report.xlsx', secrets=secrets)
    assert not (tmp_path / 'report.xlsx').exists()
    assert not (tmp_path / 'cache').exists()


@pytest.mark.parametrize('url', ['https://hodor.canalplus.pro/private', 'https://evil.example/path',
                                 'https://www.canalplus.com/?token=secret',
                                 'https://www.canalplus.com/' + 'a' * 32,
                                 'https://www.canalplus.com/%61' + 'a' * 31])
def test_only_public_urls_persist(tmp_path, rows, url):
    with pytest.raises(ValueError):
        save_snapshot([replace(rows[0], public_url=url)], tmp_path)


@pytest.mark.parametrize('mutation', [
    lambda data: data.update(schema_version=2),
    lambda data: data.update(schema_version=True),
    lambda data: data['rows'][0].update(duration_minutes=True),
    lambda data: data['rows'][0].update(expiration='invalid'),
    lambda data: data['rows'][0].update(availability_end_date=float('nan')),
    lambda data: data['rows'][0].update(tokenPass='secret'),
    lambda data: data['rows'][0].update(title='a' * 32),
])
def test_invalid_snapshot_fails_explicitly(tmp_path, rows, mutation):
    path = save_snapshot(rows, tmp_path, created_at=stamp(31))
    data = json.loads(path.read_text())
    mutation(data)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Invalid latest'):
        load_snapshot(tmp_path)


def test_excel_failure_keeps_previous_workbook(tmp_path, rows, monkeypatch):
    import mycanal_expiry_tracker.excel as excel
    path = tmp_path / 'report.xlsx'
    path.write_bytes(b'previous workbook')
    monkeypatch.setattr(excel, '_write_excel', Mock(side_effect=OSError('failed')))
    with pytest.raises(OSError):
        write_excel(rows, path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == {'report.xlsx': b'previous workbook'}
