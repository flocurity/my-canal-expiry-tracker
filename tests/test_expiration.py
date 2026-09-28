from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.expiration import days_remaining, extract_expiration


def response(options):
    return {'detail': {'informations': {'contentAvailability': {'availabilities': options}}}}


def test_v5_timestamp_without_legacy_information():
    assert extract_expiration({
        'detail': {'availabilityEndDate': 1823119140000},
    }) == date(2027, 10, 9)


def test_v5_timestamp_precedes_legacy_timestamp(fixture_data):
    payload = fixture_data('detail_movie.json')
    payload['detail']['availabilityEndDate'] = 1823119140000
    assert extract_expiration(payload) == date(2027, 10, 9)


@pytest.mark.parametrize('value', [
    None, True, '', '1823119140000', 'invalid', [], {},
    float('nan'), float('inf'), 10 ** 1000,
])
@pytest.mark.parametrize('fixture', ['detail_movie.json', 'detail_stream_label.json'])
def test_invalid_v5_timestamp_falls_back_to_legacy(fixture_data, fixture, value):
    payload = fixture_data(fixture)
    payload['detail']['availabilityEndDate'] = value
    assert extract_expiration(payload) == date(2026, 11, 2)


def test_invalid_v5_timestamp_without_legacy_date():
    assert extract_expiration({'detail': {'availabilityEndDate': 'invalid'}}) is None


def test_v5_timestamp_uses_paris_calendar_date():
    timestamp = datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc).timestamp() * 1000
    assert extract_expiration({
        'detail': {'availabilityEndDate': timestamp},
    }) == date(2026, 7, 2)


def test_download_timestamp_preferred(fixture_data):
    data = fixture_data('detail_movie.json')
    data['detail']['informations']['contentAvailability']['availabilities']['stream']['label'] = "Dispo. jusqu'au 01/01/2030"
    assert extract_expiration(data) == date(2026, 11, 2)


def test_stream_label(fixture_data):
    assert extract_expiration(fixture_data('detail_stream_label.json')) == date(2026, 11, 2)


@pytest.mark.parametrize('month, hour', [(1, 23), (7, 22)])
def test_timestamp_uses_paris_calendar_date(month, hour):
    timestamp = datetime(2026, month, 1, hour, 30, tzinfo=timezone.utc).timestamp() * 1000
    assert extract_expiration(response({'download': {'availabilityEndDate': timestamp}})) == date(2026, month, 2)


def test_other_timestamp_before_labels():
    assert extract_expiration(response({
        'download': {'availabilityEndDate': 'bad'},
        'stream': {'label': "Dispo. jusqu'au 01/01/2030"},
        'other': {'availabilityEndDate': 1793660340000},
    })) == date(2026, 11, 2)


@pytest.mark.parametrize('value', [None, True, '1793660340000', float('inf'), 10 ** 1000])
def test_bad_timestamp_falls_back(value):
    assert extract_expiration(response({
        'download': {'availabilityEndDate': value},
        'stream': {'label': 'Dispo. jusqu’au 02/11/2026'},
    })) == date(2026, 11, 2)


@pytest.mark.parametrize('options', [None, [], {}, {'stream': None}, {'download': []},
                                     {'stream': {'label': "Dispo. jusqu'au 31/02/2026"}},
                                     {'stream': {'label': 123}}])
def test_unknown_date(options):
    assert extract_expiration(response(options)) is None


@pytest.mark.parametrize('name', ['detail_show.json', 'detail_season.json'])
def test_real_series_shape_has_no_availability(fixture_data, name):
    assert extract_expiration(fixture_data(name)) is None


@pytest.mark.parametrize('payload', [None, [], {}, {'detail': []}])
def test_invalid_detail(payload):
    with pytest.raises(ValueError):
        extract_expiration(payload)


@pytest.mark.parametrize('offset', [-1, 0, 2, 3, 7, 8, 30, 31])
def test_days_remaining(offset):
    from datetime import timedelta
    today = date(2026, 10, 1)
    assert days_remaining(today + timedelta(days=offset), today) == offset
    assert days_remaining(None, today) is None


def test_documentary_timestamp_with_nondated_label(fixture_data):
    payload = fixture_data('detail_documentary.json')
    expected = datetime.fromtimestamp(1942696740000 / 1000, timezone.utc).astimezone(
        ZoneInfo('Europe/Paris')
    ).date()
    assert extract_expiration(payload) == expected
