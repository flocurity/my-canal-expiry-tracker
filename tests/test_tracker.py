from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from src.cache import DetailCache
from src.detail import DetailData
from src.excel import build_dataframe
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


def test_raw_cache_does_not_fetch_for_missing_subgenre(tmp_path, item):
    cache = DetailCache(tmp_path / 'cache.json')
    cache.put(item.content_id, DetailData(1793660340000))
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
    payload = fixture_data('detail_show.json')
    payload['detail'].pop('subgenre')
    payload['tracking']['dataLayer'].pop('subgenre')
    client.fetch.return_value = payload
    result = process_items([item], client, DetailCache(tmp_path / 'cache.json'))[0]
    assert result.subgenre == ''
    assert result.status == 'Date inconnue'


@pytest.mark.parametrize('supports_v5', [False, True])
def test_query_changes_reuse_enrichment_until_refresh(tmp_path, item, fixture_data, supports_v5):
    from src.canal_api import build_detail_url

    item = replace(item, supports_detail_v5=supports_v5)
    path = tmp_path / 'cache.json'
    cache = DetailCache(path)
    cache.put(item.content_id, DetailData(subgenre='legacy'))
    cache.save()
    client = Mock()
    payload = fixture_data('detail_show.json')
    payload['detail']['subgenre'] = 'Série Science-fiction'
    client.fetch.return_value = payload
    result = process_items([item], client, DetailCache(path))[0]
    assert result.subgenre == 'legacy'
    assert result.status == 'Date inconnue'
    client.fetch.assert_not_called()
    refreshed = process_items([item], client, DetailCache(path), refresh=True)[0]
    assert refreshed.subgenre == 'Série Science-fiction'
    client.fetch.assert_called_once_with(
        build_detail_url(item.detail_url, supports_v5), item.content_id,
    )


def test_v5_duration_and_availability_survive_cache(tmp_path, item, fixture_data):
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie_v5.json')
    path = tmp_path / 'details.json'
    first = process_items([item], client, DetailCache(path))
    assert first[0].duration_minutes == 98
    assert build_dataframe(first)['Durée'].iloc[0] == 98 / 1440
    assert first[0].availability_text == 'samedi 9 octobre 23h59'
    assert process_items([item], client, DetailCache(path)) == first
    client.fetch.assert_called_once()


@pytest.mark.parametrize('minutes, expected', [(107, 107 / 1440), (133, 133 / 1440),
                                               (60, 60 / 1440), (47, 47 / 1440)])
def test_movie_duration(minutes, expected, fixture_data, item):
    from src.tracker import extract_duration
    payload = fixture_data('detail_movie_v5.json')
    payload['detail']['duration'] = minutes
    extracted = extract_duration(payload)
    assert extracted == minutes
    from src.tracker import ContentResult
    result = ContentResult(item, None, 'Date inconnue', duration_minutes=extracted)
    assert build_dataframe([result])['Durée'].iloc[0] == expected


@pytest.mark.parametrize('value', [None, True, 0, -1, '107', 107.5, [], {}, float('inf')])
def test_unusable_duration(value):
    from src.tracker import extract_duration
    assert extract_duration({'detail': {'genre': 'Cinéma', 'duration': value}}) is None


@pytest.mark.parametrize('name', ['detail_movie.json', 'detail_show.json', 'detail_season.json'])
def test_missing_duration(name, fixture_data):
    from src.tracker import extract_duration
    assert extract_duration(fixture_data(name)) is None


def test_series_duration_never_used():
    from src.tracker import extract_duration
    assert extract_duration({'detail': {'genre': 'Séries', 'duration': 107}}) is None


def test_legacy_cache_is_replaced_safely(tmp_path, item, fixture_data):
    import json
    from datetime import datetime, timezone
    path = tmp_path / 'details.json'
    path.write_text(json.dumps({item.content_id: {
        'retrieved_at': datetime.now(timezone.utc).isoformat(),
        'url': item.detail_url, 'expiration': '2026-09-30',
        'duration': '1 h 38 min', 'availability_text': 'mercredi 30 septembre 23h59',
        'status': 'OK', 'subgenre': 'old',
    }}))
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie.json')
    result = process_items([item], client, DetailCache(path))[0]
    assert result.expiration == date(2026, 11, 2)
    assert result.subgenre == 'Film Science-fiction'
    client.fetch.assert_called_once_with(item.detail_url, item.content_id)
    assert set(json.loads(path.read_text())[item.content_id]) == {
        'retrieved_at', 'availability_end_date', 'subgenre',
    }


def token_url(token, content_id='29703662_50662'):
    # Sanitized tokens model the two working URLs from the Vicious regression.
    return (f'https://hodor.canalplus.pro/api/v2/mycanal/detail/{token}/okapi/'
            f'{content_id}.json?detailType=detailPage&objectType=unit')


def test_vicious_token_change_reuses_fresh_enrichment(tmp_path, item, fixture_data):
    old = replace(item, content_id='29703662_50662', detail_url=token_url('a' * 32))
    current = replace(old, detail_url=token_url('b' * 32), title='Current title',
                      service='Current service', in_offer=False, duration_ms=5880000)
    path = tmp_path / 'details.json'
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie_v5.json')
    process_items([old], client, DetailCache(path))
    client.reset_mock()
    result = process_items([current], client, DetailCache(path))[0]
    client.fetch.assert_not_called()
    assert result.item == current
    frame = build_dataframe([result])
    assert frame['Titre'].iloc[0] == 'Current title'
    assert frame['Service'].iloc[0] == 'Current service'
    assert frame["Dans l'offre"].iloc[0] == 'Non'
    assert frame['Durée'].iloc[0] == 98 / 1440
    assert 'https://' not in path.read_text()
    assert 'a' * 32 not in path.read_text()
    assert 'b' * 32 not in path.read_text()


@pytest.mark.parametrize('reason', ['missing', 'expired', 'refresh'])
def test_fetch_uses_current_url(tmp_path, item, fixture_data, reason):
    from datetime import datetime, timedelta, timezone
    from src.canal_api import build_detail_url
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    if reason != 'missing':
        cache.put(item.content_id, DetailData())
        if reason == 'expired':
            cache.entries[item.content_id]['retrieved_at'] = (
                datetime.now(timezone.utc) - timedelta(hours=25)
            ).isoformat()
        cache.save()
    current = replace(item, detail_url=token_url('b' * 32, item.content_id),
                      supports_detail_v5=True)
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie.json')
    process_items([current], client, DetailCache(path), refresh=reason == 'refresh')
    client.fetch.assert_called_once_with(build_detail_url(current.detail_url, True), item.content_id)
    assert DetailCache(path).get(item.content_id).availability_end_date == 1793660340000


def test_export_with_97_cached_and_three_new_items(tmp_path, item, fixture_data):
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    for index in range(97):
        cache.put(str(index), DetailData(1790805540000, subgenre='Film Horreur'))
    cache.save()
    items = [replace(item, content_id=str(i), detail_url=token_url('b' * 32, str(i)))
             for i in range(100)]
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie_v5.json')
    results = process_items(items, client, DetailCache(path))
    assert len(results) == 100
    assert client.fetch.call_count == 3
    assert [call.args[1] for call in client.fetch.call_args_list] == ['97', '98', '99']
    assert all(result.availability_text == 'mercredi 30 septembre 23h59'
               for result in results[:97])


def test_season_resource_changes_invalidate_scalar_detail_cache(tmp_path, item):
    cache = DetailCache(tmp_path / 'details.json')
    detail = DetailData(1790805540000)
    cache.put(item.content_id, detail, 'fiction_season1')
    assert cache.get(item.content_id, 'fiction_season1') == detail
    assert cache.get(item.content_id, 'fiction_season2') is None
    assert cache.get(item.content_id) is None


@pytest.mark.parametrize('failure', [DetailError('HTTP 403'), ValueError('invalid detail')])
def test_refresh_failure_preserves_previous_raw_entry(tmp_path, item, failure):
    cache = DetailCache(tmp_path / 'details.json')
    detail = DetailData(1790805540000)
    cache.put(item.content_id, detail)
    cache.save()
    client = Mock()
    client.fetch.side_effect = failure
    result = process_items([item], client, cache, refresh=True)[0]
    assert result.status in ('Erreur HTTP', 'Erreur parsing')
    assert result.expiration is None
    assert DetailCache(cache.path).get(item.content_id) == detail


def test_label_only_fallback_survives_raw_cache(tmp_path, item, fixture_data):
    client = Mock()
    client.fetch.return_value = fixture_data('detail_stream_label.json')
    path = tmp_path / 'details.json'
    first = process_items([item], client, DetailCache(path))
    assert first[0].expiration == date(2026, 11, 2)
    assert first[0].availability_text == ''
    assert process_items([item], client, DetailCache(path)) == first
    client.fetch.assert_called_once()
    raw = DetailCache(path).get(item.content_id)
    assert raw.availability_end_date is None
    assert raw.availability_label == "Dispo. jusqu'au 02/11/2026"


def test_playlist_duration_does_not_enter_cache(tmp_path, item, fixture_data):
    import json
    item = replace(item, duration_ms=5880000)
    client = Mock()
    client.fetch.return_value = fixture_data('detail_movie_v5.json')
    path = tmp_path / 'details.json'
    first = process_items([item], client, DetailCache(path))
    assert build_dataframe(first)['Durée'].iloc[0] == 98 / 1440
    assert set(json.loads(path.read_text())[item.content_id]) == {
        'retrieved_at', 'availability_end_date', 'subgenre',
    }
    updated = replace(item, duration_ms=7980000)
    second = process_items([updated], client, DetailCache(path))
    assert build_dataframe(second)['Durée'].iloc[0] == 133 / 1440
    client.fetch.assert_called_once()
