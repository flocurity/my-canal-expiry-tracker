from mycanal_expiry_tracker.report import to_report_rows
from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from mycanal_expiry_tracker.excel import build_dataframe
from mycanal_expiry_tracker.canal_api import DetailError
from mycanal_expiry_tracker.tracker import extract_subgenre, process_items


def test_continues_after_item_failure(tmp_path, item, fixture_data):
    client = Mock(authentication=None)
    client.fetch.side_effect = [DetailError('HTTP 403'), fixture_data('detail_movie.json'),
                               {'detail': None}, fixture_data('detail_show.json')]
    items = [replace(item, content_id=str(i)) for i in range(4)]
    results = process_items(items, client)
    assert [result.status for result in results] == ['Erreur HTTP', 'OK', 'Erreur parsing', 'Date inconnue']
    assert len(results) == 4
    assert results[1].expiration == date(2026, 11, 2)


def test_missing_subgenre_in_detail(tmp_path, item, fixture_data):
    client = Mock(authentication=None)
    payload = fixture_data('detail_show.json')
    payload['detail'].pop('subgenre')
    payload['tracking']['dataLayer'].pop('subgenre')
    client.fetch.return_value = payload
    result = process_items([item], client)[0]
    assert result.subgenre == ''
    assert result.status == 'Date inconnue'


def test_v5_duration_and_availability_are_fresh(tmp_path, item, fixture_data):
    client = Mock(authentication=None)
    client.fetch.return_value = fixture_data('detail_movie_v5.json')
    first = process_items([item], client)
    assert first[0].duration_minutes == 98
    assert build_dataframe(to_report_rows(first))['Durée'].iloc[0] == 98 / 1440
    assert first[0].availability_text == 'samedi 9 octobre 23h59'
    assert process_items([item], client) == first
    assert client.fetch.call_count == 2


@pytest.mark.parametrize('minutes, expected', [(107, 107 / 1440), (133, 133 / 1440),
                                               (60, 60 / 1440), (47, 47 / 1440)])
def test_movie_duration(minutes, expected, fixture_data, item):
    from mycanal_expiry_tracker.tracker import extract_duration
    payload = fixture_data('detail_movie_v5.json')
    payload['detail']['duration'] = minutes
    extracted = extract_duration(payload)
    assert extracted == minutes
    from mycanal_expiry_tracker.tracker import ContentResult
    result = ContentResult(item, None, 'Date inconnue', duration_minutes=extracted)
    assert build_dataframe(to_report_rows([result]))['Durée'].iloc[0] == expected


@pytest.mark.parametrize('value', [None, True, 0, -1, '107', 107.5, [], {}, float('inf')])
def test_unusable_duration(value):
    from mycanal_expiry_tracker.tracker import extract_duration
    assert extract_duration({'detail': {'genre': 'Cinéma', 'duration': value}}) is None


@pytest.mark.parametrize('name', ['detail_movie.json', 'detail_show.json', 'detail_season.json'])
def test_missing_duration(name, fixture_data):
    from mycanal_expiry_tracker.tracker import extract_duration
    assert extract_duration(fixture_data(name)) is None


def test_series_duration_never_used():
    from mycanal_expiry_tracker.tracker import extract_duration
    assert extract_duration({'detail': {'genre': 'Séries', 'duration': 107}}) is None


def token_url(token, content_id='29703662_50662'):
    # Sanitized tokens model the two working URLs from the Vicious regression.
    return (f'https://hodor.canalplus.pro/api/v2/mycanal/detail/{token}/okapi/'
            f'{content_id}.json?detailType=detailPage&objectType=unit')


def test_fetch_uses_current_url(tmp_path, item, fixture_data):
    from mycanal_expiry_tracker.canal_api import build_detail_url
    current = replace(item, detail_url=token_url('b' * 32, item.content_id),
                      supports_detail_v5=True)
    client = Mock(authentication=None)
    client.fetch.return_value = fixture_data('detail_movie.json')
    result = process_items([current], client)
    client.fetch.assert_called_once_with(build_detail_url(current.detail_url, True), item.content_id)
    assert result[0].expiration == date(2026, 11, 2)


def test_label_only_fallback_is_fresh(tmp_path, item, fixture_data):
    client = Mock(authentication=None)
    client.fetch.return_value = fixture_data('detail_stream_label.json')
    first = process_items([item], client)
    assert first[0].expiration == date(2026, 11, 2)
    assert first[0].availability_text == ''
    assert process_items([item], client) == first
    assert client.fetch.call_count == 2
