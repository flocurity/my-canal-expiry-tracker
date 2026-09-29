import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from src.cache import DetailCache
from src.canal_api import DetailError
from src.playlist import load_playlist
from src.series import parse_duration_label
from src.tracker import process_items


@pytest.fixture
def series(item):
    return replace(item, content_id='squirtle_brand', title='Squirtle',
                   content_type='folder', subtitle='Saison 3',
                   season_id='squirtle_s3', episode_id='squirtle_s3e3',
                   user_progress=64, supports_detail_v5=True)


@pytest.fixture
def client(fixture_data):
    client = Mock()
    client.fetch.return_value = fixture_data('detail_series_v5.json')
    client.fetch_episodes.return_value = fixture_data('episodes_series.json')
    return client


def season_response(template, number, durations, seasons):
    """Synthetic variants retain the inspected episodes/selector nesting."""
    result = deepcopy(template)
    result['episodes']['contents'] = [
        {'contentID': f'squirtle_s{number}e{index}', 'seasonNumber': number,
         'episodeNumber': index, 'durationLabel': duration,
         'availabilityEndDate': 1823119140000}
        for index, duration in enumerate(durations, start=1)
    ]
    result['episodes']['paging']['nbContents'] = len(durations)
    result['selector'] = [
        {'contentID': f'squirtle_s{season}', 'seasonNumber': season,
         'onClick': {'URLPage': episodes_url(season)}} for season in seasons
    ]
    return result


def episodes_url(number):
    return ('https://hodor.canalplus.pro/api/v2/mycanal/episodes/' + 'a' * 32
            + f'/squirtle_brand?seasonID=squirtle_s{number}')


@pytest.mark.parametrize('label, expected', [
    ('57 min', 57), ('1h02', 62), ('1h31', 91), (' 1 h 02 min ', 62),
    (None, None), ('unknown', None), ('1h99', None), (True, None), ('0 min', None),
])
def test_duration_labels(label, expected):
    assert parse_duration_label(label) == expected


def test_playlist_wins_inclusive_resume_and_expiration(tmp_path, series, client):
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == 'S3E3'
    assert result.episodes_remaining == 9
    assert result.duration_minutes == 211
    assert result.expiration == date(2026, 9, 30)
    assert result.availability_text == 'mercredi 30 septembre 23h59'
    client.fetch.assert_called_once()
    client.fetch_episodes.assert_called_once()
    assert parse_qs(urlsplit(client.fetch_episodes.call_args.args[0]).query)['seasonID'] == ['squirtle_s3']


def test_cached_catalog_uses_new_playlist_resume_and_token(tmp_path, series, client):
    for episode in client.fetch_episodes.return_value['episodes']['contents'][4:]:
        episode['availabilityEndDate'] = 1823119140000
    path = tmp_path / 'details.json'
    process_items([series], client, DetailCache(path))
    client.reset_mock()
    updated = replace(series, episode_id='squirtle_s3e5', user_progress=1,
                      detail_url=series.detail_url.replace('/fiction/', '/' + 'b' * 32 + '/'))
    result = process_items([updated], client, DetailCache(path))[0]
    assert result.resume_episode == 'S3E5'
    assert result.episodes_remaining == 7
    assert result.duration_minutes == 169
    assert result.expiration == date(2027, 10, 9)
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()
    raw = json.loads(path.read_text())
    catalog = raw['season:squirtle_brand:squirtle_s3']['catalog']
    assert set(catalog) == {'season', 'seasons', 'episodes'}
    assert set(catalog['episodes'][0]) == {
        'content_id', 'number', 'duration_minutes', 'availability_end_date',
    }
    for forbidden in ['https://', 'userProgress', 'isCompleted', 'resume_episode',
                      'tokenPass', 'a' * 32, 'b' * 32, 'S3E3', 'S3E5']:
        assert forbidden not in path.read_text()


def test_current_season_url_overrides_conflicting_detail_season(tmp_path, series, client):
    action = client.fetch.return_value['actionLayout']['primaryActions'][0]
    action['onClick']['URLEpisodesList'] = episodes_url(1)
    action['tracking']['dataLayer']['seasonNumber'] = 1
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == 'S3E3'
    assert client.fetch_episodes.call_args.args[0] == episodes_url(3)


@pytest.mark.parametrize('resume', ['squirtle_s3e1', 'squirtle_s3e3'])
def test_later_seasons_and_no_per_episode_requests(tmp_path, series, client, fixture_data, resume):
    template = fixture_data('episodes_series.json')
    catalogs = {3: season_response(template, 3, ['21 min'] * 11, [1, 2, 3, 5, 8]),
                5: season_response(template, 5, ['57 min'] * 10, [1, 2, 3, 5, 8]),
                8: season_response(template, 8, ['1h02'] * 8, [1, 2, 3, 5, 8])}
    def fetch(url, content_id):
        number = int(parse_qs(urlsplit(url).query)['seasonID'][0].removeprefix('squirtle_s'))
        return catalogs[number]
    client.fetch_episodes.side_effect = fetch
    series = replace(series, episode_id=resume)
    path = tmp_path / 'details.json'
    result = process_items([series], client, DetailCache(path))[0]
    current_count = 11 if resume.endswith('e1') else 9
    assert result.episodes_remaining == current_count + 18
    assert result.duration_minutes == current_count * 21 + 570 + 496
    assert client.fetch_episodes.call_count == 3
    client.reset_mock()
    assert process_items([series], client, DetailCache(path))[0] == result
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()
    # One expired catalog must not trigger another request for the other two.
    cache = DetailCache(path)
    cache.entries['season:squirtle_brand:squirtle_s5']['retrieved_at'] = (
        datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert process_items([series], client, cache)[0] == result
    client.fetch_episodes.assert_called_once_with(episodes_url(5), series.content_id)
    client.reset_mock()
    moved = replace(series, season_id='squirtle_s5', episode_id='squirtle_s5e2',
                    detail_url=series.detail_url.replace('detailPage', 'detailSeason'))
    result = process_items([moved], client, cache)[0]
    assert result.resume_episode == 'S5E2'
    assert result.episodes_remaining == 17
    assert result.subgenre == 'Série Animation'
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()


def test_not_started_fallback_all_five_seasons(tmp_path, series, client, fixture_data):
    series = replace(series, season_id='', episode_id='', user_progress=None)
    action = client.fetch.return_value['actionLayout']['primaryActions'][0]
    action['onClick']['URLEpisodesList'] = episodes_url(1)
    action['onClick']['contentID'] = 'squirtle_s1e1'
    # Alternate observed-compatible tracking nesting under onClick.
    action['onClick']['tracking'] = {'dataLayer': {'seasonNumber': 1, 'episodeNumber': 1}}
    del action['tracking']
    first = ['1h02'] * 4 + ['57 min'] * 3 + ['55 min', '46 min', '1h13']
    template = fixture_data('episodes_series.json')
    client.fetch_episodes.side_effect = [season_response(template, n, first if n == 1 else ['1h31'], range(1, 6))
                                        for n in range(1, 6)]
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == 'S1E1'
    assert result.episodes_remaining == 14
    assert result.duration_minutes == 593 + 4 * 91
    assert client.fetch_episodes.call_count == 5


def test_single_season_and_unordered_episode_number_fallback(tmp_path, series, client, fixture_data):
    series = replace(series, season_id='squirtle_s1', episode_id='missing',
                     season_number=1, episode_number=1)
    catalog = season_response(fixture_data('episodes_series.json'), 1,
                              [f'{n} min' for n in [50, 49, 43, 48, 47, 48, 49, 54]], [1])
    catalog['episodes']['contents'].reverse()
    client.fetch_episodes.return_value = catalog
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == 'S1E1'
    assert result.episodes_remaining == 8
    assert result.duration_minutes == 388
    client.fetch_episodes.assert_called_once()


@pytest.mark.parametrize('bad_duration', [None, 'unparseable'])
def test_missing_duration_leaves_total_blank_but_count_known(tmp_path, series, client, bad_duration):
    client.fetch_episodes.return_value['episodes']['contents'][2]['durationLabel'] = bad_duration
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.episodes_remaining == 9
    assert result.duration_minutes is None
    assert result.expiration == date(2026, 9, 30)


def test_missing_expiration_uses_known_remaining_dates_only(tmp_path, series, client):
    contents = client.fetch_episodes.return_value['episodes']['contents']
    for episode in contents[2:]:
        episode.pop('availabilityEndDate')
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.expiration is None
    assert result.status == 'Date inconnue'
    assert result.episodes_remaining == 9
    contents[-1]['availabilityEndDate'] = 1790805540000
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'), refresh=True)[0]
    assert result.expiration == date(2026, 9, 30)


@pytest.mark.parametrize('problem', ['resume', 'selector', 'pagination', 'previous_page',
                                     'coordinates', 'duplicates', 'missing_resume'])
def test_incomplete_series_never_presents_complete_totals(tmp_path, series, client, problem):
    payload = client.fetch_episodes.return_value
    if problem == 'resume':
        series = replace(series, episode_id='not_found')
    elif problem == 'selector':
        payload.pop('selector')
    elif problem == 'pagination':
        payload['episodes']['paging']['hasNextPage'] = True
    elif problem == 'previous_page':
        payload['episodes']['paging']['hasPreviousPage'] = True
    elif problem == 'coordinates':
        del payload['episodes']['contents'][0]['episodeNumber']
    elif problem == 'duplicates':
        payload['episodes']['contents'].append(payload['episodes']['contents'][0])
    else:
        series = replace(series, season_id='', episode_id='')
        client.fetch.return_value['actionLayout'] = {}
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == ''
    assert result.episodes_remaining is None
    assert result.duration_minutes is None
    assert result.expiration is None
    assert result.status == 'Série incomplète'
    assert result.subgenre == 'Série Animation'


def test_failed_refresh_keeps_previous_catalog(tmp_path, series, client):
    path = tmp_path / 'details.json'
    process_items([series], client, DetailCache(path))
    old = DetailCache(path).get_season(series.content_id, series.season_id)
    client.fetch_episodes.side_effect = DetailError('HTTP 403')
    result = process_items([series], client, DetailCache(path), refresh=True)[0]
    assert result.episodes_remaining is None
    assert result.status == 'Erreur HTTP'
    assert DetailCache(path).get_season(series.content_id, series.season_id) == old


def test_playlist_resume_fields_are_preserved(tmp_path, fixture_data):
    raw = fixture_data('playlist.json')['contents'][1]
    raw.update(seasonID='squirtle_s3', episodeID='squirtle_s3e3', userProgress=64,
               seasonNumber=3, episodeNumber=3)
    (tmp_path / 'playlist.json').write_text(json.dumps({'contents': [raw]}))
    item = load_playlist(tmp_path)[0]
    assert (item.season_id, item.episode_id, item.user_progress) == ('squirtle_s3', 'squirtle_s3e3', 64)
    assert (item.season_number, item.episode_number) == (3, 3)


def test_partial_count_and_legacy_selector_fallback(tmp_path, series, client, fixture_data):
    payload = client.fetch_episodes.return_value
    payload['episodes']['contents'].pop()
    result = process_items([series], client, DetailCache(tmp_path / 'partial.json'))[0]
    assert result.episodes_remaining is None
    assert result.status == 'Série incomplète'
    payload = fixture_data('episodes_series.json')
    selector = payload.pop('selector')
    client.fetch.return_value['detail']['seasons'] = selector
    client.fetch_episodes.return_value = payload
    result = process_items([series], client, DetailCache(tmp_path / 'legacy.json'))[0]
    assert result.resume_episode == 'S3E3'
    assert result.episodes_remaining == 9


def test_failed_later_season_does_not_publish_partial_backlog(tmp_path, series, client, fixture_data):
    template = fixture_data('episodes_series.json')
    client.fetch_episodes.side_effect = [
        season_response(template, 3, ['21 min'] * 11, [3, 5]), DetailError('HTTP 503'),
    ]
    cache = DetailCache(tmp_path / 'details.json')
    result = process_items([series], client, cache)[0]
    assert result.episodes_remaining is None
    assert result.duration_minutes is None
    assert result.expiration is None
    assert result.resume_episode == 'S3E3'
    assert cache.get_season(series.content_id, 'squirtle_s3') is not None
    assert cache.get_season(series.content_id, 'squirtle_s5') is None


def test_corrupt_cached_catalog_is_a_miss_without_retaining_urls(tmp_path, series, client):
    path = tmp_path / 'details.json'
    process_items([series], client, DetailCache(path))
    raw = json.loads(path.read_text())
    entry = raw['season:squirtle_brand:squirtle_s3']
    entry['URLPage'] = 'https://example.invalid/private'
    entry['catalog']['episodes'][0]['URLPage'] = 'https://example.invalid/private'
    path.write_text(json.dumps(raw))
    clean = DetailCache(path)
    assert clean.get_season(series.content_id, series.season_id) is not None
    clean.save()
    assert 'https://' not in path.read_text()
    raw = json.loads(path.read_text())
    del raw['season:squirtle_brand:squirtle_s3']['catalog']['episodes'][0]['number']
    path.write_text(json.dumps(raw))
    assert DetailCache(path).get_season(series.content_id, series.season_id) is None
