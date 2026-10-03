import json
from datetime import datetime, timedelta, timezone

import pytest

from mycanal_expiry_tracker.cache import DetailCache
from mycanal_expiry_tracker.detail import DetailData


def test_cache_roundtrip_including_unknown(tmp_path, item):
    path = tmp_path / 'cache' / 'details.json'
    cache = DetailCache(path)
    assert cache.get(item.content_id) is None
    cache.put(item.content_id, DetailData(1793660340000))
    cache.put('unknown', DetailData())
    cache.save()
    loaded = DetailCache(path)
    assert loaded.get(item.content_id) == DetailData(1793660340000)
    assert loaded.get('unknown') == DetailData()
    assert not list(path.parent.glob('*.tmp'))


@pytest.mark.parametrize('age', [timedelta(hours=25), timedelta(hours=-1)])
def test_cache_expiration(tmp_path, age):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', DetailData())
    cache.entries['id']['retrieved_at'] = (datetime.now(timezone.utc) - age).isoformat()
    assert cache.get('id') is None


@pytest.mark.parametrize('value', ['bad json', '[]', '{"id":null}', '{"id":{"retrieved_at":3}}'])
def test_corrupt_cache_is_a_miss(tmp_path, value):
    path = tmp_path / 'details.json'
    path.write_text(value)
    assert DetailCache(path).get('id') is None


def test_malformed_entry(tmp_path):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', DetailData())
    cache.entries['id']['availability_end_date'] = 'not-a-timestamp'
    assert cache.get('id') is None
    cache.put('', DetailData())
    assert '' not in cache.entries


def test_write_failure_is_recoverable(tmp_path, monkeypatch):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', DetailData())
    monkeypatch.setattr('mycanal_expiry_tracker.cache.os.replace', lambda *args: (_ for _ in ()).throw(OSError('disk full')))
    cache.save()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('subgenre', [None, 3, False, [], {}, '', ' \t'])
def test_unusable_cached_subgenre_keeps_date(tmp_path, subgenre):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', DetailData(1793660340000))
    cache.entries['id']['subgenre'] = subgenre
    assert cache.get('id') == DetailData(1793660340000)


def test_cache_preserves_subgenre_verbatim(tmp_path):
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    cache.put('id', DetailData(subgenre='  Science-FICTION / mystère  '))
    cache.save()
    assert DetailCache(path).get('id') == DetailData(subgenre='  Science-FICTION / mystère  ')


def test_serialization_contains_only_raw_detail_enrichment(tmp_path):
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    cache.put('fiction', DetailData(1790805540000, subgenre='Film Drame', duration_minutes=128))
    cache.save()
    entry = json.loads(path.read_text())['fiction']
    assert entry == {
        'retrieved_at': cache.entries['fiction']['retrieved_at'],
        'availability_end_date': 1790805540000,
        'subgenre': 'Film Drame',
        'duration_minutes': 128,
    }


def test_loading_strips_obsolete_fields_even_from_unvisited_entries(tmp_path):
    path = tmp_path / 'details.json'
    path.write_text(json.dumps({
        'old': {'url': 'https://old/token', 'expiration': '2026-09-30', 'status': 'OK'},
        'new': {'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'availability_end_date': 1790805540000, 'url': 'https://old/token',
                'duration': '98 min', 'title': 'not enrichment'},
    }))
    cache = DetailCache(path)
    assert cache.get('old') is None
    assert cache.get('new') == DetailData(1790805540000)
    cache.save()
    data = json.loads(path.read_text())
    assert set(data) == {'new'}
    assert set(data['new']) == {'retrieved_at', 'availability_end_date', 'subgenre'}


@pytest.mark.parametrize('value', [True, '1790805540000', float('inf'), [], {}, 10 ** 1000])
def test_invalid_raw_timestamp_is_a_miss(tmp_path, value):
    cache = DetailCache(tmp_path / 'details.json')
    cache.put('id', DetailData())
    cache.entries['id']['availability_end_date'] = value
    assert cache.get('id') is None


def test_missing_cache_has_no_failure_diagnostic(tmp_path):
    from structlog.testing import capture_logs
    with capture_logs() as logs:
        cache = DetailCache(tmp_path / 'missing.json')
    assert cache.entries == {}
    assert not any('failure_debug' in entry['event'] for entry in logs)


@pytest.mark.parametrize('number', [0, 1, -1, True, False, '0', 0.0, None, [], {}])
def test_cached_season_number_contract(number):
    from mycanal_hodor_core.episodes import Episode, Season, SeasonCatalog
    from mycanal_expiry_tracker.catalog_cache import catalog_from_cache, catalog_to_cache
    season = Season('season_mammouth', number)
    catalog = SeasonCatalog(season, (season,), (
        Episode('26219525_50006', 2621952550006, 21, None, 'Mammouth'),
        Episode('unit_gptou', 2, 30, 1790805540000),
    ))
    raw = json.loads(json.dumps(catalog_to_cache(catalog)))
    if type(number) is int and number >= 0:
        assert catalog_from_cache(raw) == catalog
        assert [e.content_id for e in catalog_from_cache(raw).episodes] == [
            '26219525_50006', 'unit_gptou']
    else:
        with pytest.raises(ValueError, match='Invalid cached season'):
            catalog_from_cache(raw)


def test_resume_fallback_cache_preserves_zero(tmp_path):
    from mycanal_expiry_tracker.detail import ResumeFallback
    path = tmp_path / 'details.json'
    fallback = ResumeFallback('season_mammouth', 'unit_gptou', 0, 2)
    cache = DetailCache(path)
    cache.put('brand_mammouth', DetailData(resume_fallback=fallback))
    cache.save()
    assert DetailCache(path).get('brand_mammouth').resume_fallback == fallback
