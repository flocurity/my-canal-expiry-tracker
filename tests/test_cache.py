import json
from datetime import date, datetime, timedelta, timezone

import pytest

from src.cache import DetailCache


def test_cache_roundtrip_including_unknown(tmp_path, item):
    path = tmp_path / 'cache' / 'details.json'
    cache = DetailCache(path)
    assert cache.get(item.content_id, item.detail_url) == (False, None, '', '', '')
    cache.put(item.content_id, item.detail_url, date(2026, 11, 2))
    cache.put('unknown', item.detail_url, None)
    cache.save()
    loaded = DetailCache(path)
    assert loaded.get(item.content_id, item.detail_url) == (True, date(2026, 11, 2), '', '', '')
    assert loaded.get('unknown', item.detail_url) == (True, None, '', '', '')
    assert loaded.get(item.content_id, item.detail_url + '&changed=1') == (False, None, '', '', '')
    assert not list(path.parent.glob('*.tmp'))


@pytest.mark.parametrize('age', [timedelta(hours=25), timedelta(hours=-1)])
def test_cache_expiration(tmp_path, age):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', 'url', None)
    cache.entries['id']['retrieved_at'] = (datetime.now(timezone.utc) - age).isoformat()
    assert cache.get('id', 'url') == (False, None, '', '', '')


@pytest.mark.parametrize('value', ['bad json', '[]', '{"id":null}', '{"id":{"retrieved_at":3}}'])
def test_corrupt_cache_is_a_miss(tmp_path, value):
    path = tmp_path / 'details.json'
    path.write_text(value)
    assert DetailCache(path).get('id', 'url') == (False, None, '', '', '')


def test_malformed_entry(tmp_path):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', 'url', None)
    cache.entries['id']['expiration'] = 'not-a-date'
    assert cache.get('id', 'url') == (False, None, '', '', '')
    cache.put('', 'url', None)
    assert '' not in cache.entries


def test_write_failure_is_recoverable(tmp_path, monkeypatch):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', 'url', None)
    monkeypatch.setattr('src.cache.os.replace', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    cache.save()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('subgenre', [None, 3, False, [], {}, '', ' \t'])
def test_unusable_cached_subgenre_keeps_date(tmp_path, subgenre):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', 'url', date(2026, 11, 2))
    cache.entries['id']['subgenre'] = subgenre
    assert cache.get('id', 'url') == (True, date(2026, 11, 2), '', '', '')


def test_cache_preserves_subgenre_verbatim(tmp_path):
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    cache.put('id', 'url', None, '  Science-FICTION / mystère  ')
    cache.save()
    assert DetailCache(path).get('id', 'url') == (
        True, None, '  Science-FICTION / mystère  ', '', '',
    )
