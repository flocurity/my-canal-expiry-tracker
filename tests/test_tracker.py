from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from src.cache import DetailCache
from src.canal_api import DetailError
from src.tracker import extract_subgenre, process_items


@pytest.mark.parametrize('tracking', [
    None, [], {}, {'dataLayer': None}, {'dataLayer': []}, {'dataLayer': {}},
    *[{'dataLayer': {'subgenre': value}} for value in (None, 42, False, [], {}, '', ' \t')],
])
def test_unusable_subgenre(tracking):
    assert extract_subgenre({'tracking': tracking}) == ''


def test_subgenre_preserved_verbatim():
    value = '  Science-FICTION / mystère  '
    assert extract_subgenre({'tracking': {'dataLayer': {'subgenre': value}}}) == value


@pytest.mark.parametrize('value', ['Série Science-fiction', '  Série Science-fiction \t'])
@pytest.mark.parametrize('tracking', [{}, {'dataLayer': {'subgenre': 'Serie Science-fiction'}}])
def test_detail_subgenre_wins_and_is_preserved(value, tracking):
    assert extract_subgenre({
        'detail': {'subgenre': value}, 'tracking': tracking,
    }) == value


@pytest.mark.parametrize('detail', [
    None, [], {},
    *[{'subgenre': value} for value in (None, 42, False, [], {}, '', ' \t\n')],
])
def test_unusable_detail_subgenre_falls_back(detail):
    value = '  Serie Science-fiction  '
    assert extract_subgenre({
        'detail': detail, 'tracking': {'dataLayer': {'subgenre': value}},
    }) == value


@pytest.mark.parametrize('value', [None, 42, False, [], {}, '', ' \t\n'])
def test_unusable_subgenre_in_both_locations(value):
    assert extract_subgenre({
        'detail': {'subgenre': value},
        'tracking': {'dataLayer': {'subgenre': value}},
    }) == ''


def test_subgenre_missing_in_both_locations():
    assert extract_subgenre({}) == ''


def test_continues_after_item_failure(tmp_path, item, fixture_data):
    client = Mock()
    client.fetch.side_effect = [DetailError('HTTP 403'), fixture_data('detail_movie.json'),
                               {'detail': None}, fixture_data('detail_show.json')]
    items = [replace(item, content_id=str(i)) for i in range(4)]
    cache = DetailCache(tmp_path / 'cache.json')
    results = process_items(items, client, cache)
    assert [result.status for result in results] == ['Erreur HTTP', 'OK', 'Erreur parsing', 'Date inconnue']
    assert len(results) == 4
    assert results[1].expiration == date(2026, 11, 2)
    assert set(cache.entries) == {'1', '3'}


def test_cache_and_refresh(tmp_path, item, fixture_data):
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie.json')
    cache = DetailCache(tmp_path / 'cache.json')
    first = process_items([item], client, cache)
    assert process_items([item], client, cache) == first
    assert client.fetch.call_count == 1
    process_items([item], client, cache, refresh=True)
    assert client.fetch.call_count == 2


def test_subgenre_survives_cached_response(tmp_path, item, fixture_data):
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie.json')
    path = tmp_path / 'cache.json'
    first = process_items([item], client, DetailCache(path))
    assert first[0].subgenre == 'Film Science-fiction'
    assert process_items([item], client, DetailCache(path)) == first
    client.fetch.assert_called_once_with(item.detail_url, item.content_id)


def test_legacy_cache_does_not_fetch_for_missing_subgenre(tmp_path, item):
    cache = DetailCache(tmp_path / 'cache.json')
    cache.put(item.content_id, item.detail_url, date(2026, 11, 2))
    del cache.entries[item.content_id]['subgenre']
    cache.save()
    client = Mock()
    result = process_items([item], client, DetailCache(cache.path))[0]
    assert result.subgenre == ''
    assert result.expiration == date(2026, 11, 2)
    assert result.status == 'OK'
    client.fetch.assert_not_called()


def test_missing_subgenre_in_detail(tmp_path, item, fixture_data):
    client = Mock()
    client.fetch.return_value = fixture_data('detail_show.json')
    result = process_items([item], client, DetailCache(tmp_path / 'cache.json'))[0]
    assert result.subgenre == ''
    assert result.status == 'Date inconnue'


@pytest.mark.parametrize('supports_v5', [False, True])
def test_cache_uses_requested_representation(tmp_path, item, fixture_data, supports_v5):
    from src.canal_api import build_detail_url

    item = replace(item, supports_detail_v5=supports_v5)
    path = tmp_path / 'cache.json'
    cache = DetailCache(path)
    cache.put(item.content_id, item.detail_url, None, 'legacy')
    cache.save()
    client = Mock()
    payload = fixture_data('detail_show.json')
    payload['detail']['subgenre'] = 'Série Science-fiction'
    client.fetch.return_value = payload
    result = process_items([item], client, DetailCache(path))[0]
    request_url = build_detail_url(item.detail_url, supports_v5)
    if supports_v5:
        client.fetch.assert_called_once_with(request_url, item.content_id)
        assert result.subgenre == 'Série Science-fiction'
        assert request_url != item.detail_url
    else:
        client.fetch.assert_not_called()
        assert result.subgenre == 'legacy'
    cached = DetailCache(path)
    assert cached.entries[item.content_id]['url'] == request_url
    assert process_items([item], client, cached)[0] == result
    assert client.fetch.call_count == int(supports_v5)
    process_items([item], client, cached, refresh=True)
    assert client.fetch.call_count == int(supports_v5) + 1
