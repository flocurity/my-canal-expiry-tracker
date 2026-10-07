import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from mycanal_expiry_tracker.cache import DetailCache
from mycanal_expiry_tracker.canal_api import DetailError
from mycanal_expiry_tracker.playlist import load_playlist
from mycanal_expiry_tracker.series import parse_duration_label
from mycanal_expiry_tracker.tracker import process_items


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




def test_playlist_wins_inclusive_resume_and_expiration(tmp_path, series, client):
    results = process_items([series], client, DetailCache(tmp_path / 'details.json'))
    assert len(results) == 1
    result = results[0]
    assert result.season_numbers == (3,)
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
        'content_id', 'number', 'duration_minutes', 'availability_end_date', 'title',
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
    client.reset_mock()
    assert process_items([series], client, DetailCache(tmp_path / 'details.json'))[0] == result
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()


def test_single_season_and_unordered_episode_number_fallback(tmp_path, series, client, fixture_data):
    series = replace(series, season_id='squirtle_s1', episode_id='missing',
                     season_number=1, episode_number=1)
    catalog = season_response(fixture_data('episodes_series.json'), 1,
                              [f'{n} min' for n in [50, 49, 43, 48, 47, 48, 49, 54]], [1])
    catalog['episodes']['contents'].reverse()
    client.fetch_episodes.return_value = catalog
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == 'S1E1'
    assert result.episodes_remaining == 1
    assert result.duration_minutes == 50
    client.fetch_episodes.assert_called_once()


@pytest.mark.parametrize('bad_duration', [None, 'unparseable'])
def test_missing_duration_leaves_total_blank_but_count_known(tmp_path, series, client, bad_duration):
    client.fetch_episodes.return_value['episodes']['contents'][2]['durationLabel'] = bad_duration
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.episodes_remaining == 9
    assert result.duration_minutes is None
    assert result.expiration == date(2026, 9, 30)


def test_missing_expiration_forms_separate_group(tmp_path, series, client):
    contents = client.fetch_episodes.return_value['episodes']['contents']
    for episode in contents[2:]:
        episode.pop('availabilityEndDate')
    result = process_items([series], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.expiration is None
    assert result.status == 'Date inconnue'
    assert result.episodes_remaining == 9
    contents[-1]['availabilityEndDate'] = 1790805540000
    results = process_items([series], client, DetailCache(tmp_path / 'details.json'), refresh=True)
    assert len(results) == 2
    unknown, known = results
    assert unknown.expiration is None
    assert unknown.episodes_remaining == 8
    assert known.expiration == date(2026, 9, 30)
    assert known.episodes_remaining == 1


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


@pytest.mark.parametrize('number,expected', [(0, 0), (1, 1), (3, 3), (-1, None), (True, None), ('0', None), (0.0, None), (None, None)])
def test_playlist_resume_fields_are_preserved(tmp_path, fixture_data, number, expected):
    raw = fixture_data('playlist.json')['contents'][1]
    raw.update(seasonID='squirtle_s3', episodeID='squirtle_s3e3', userProgress=64,
               seasonNumber=number, episodeNumber=3)
    (tmp_path / 'playlist.json').write_text(json.dumps({'contents': [raw]}))
    item = load_playlist(tmp_path)[0]
    assert (item.season_id, item.episode_id, item.user_progress) == ('squirtle_s3', 'squirtle_s3e3', 64)
    assert (item.season_number, item.episode_number) == (expected, 3)


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


def test_cached_detail_resume_fallback_request_counts(tmp_path, series, client):
    path = tmp_path / 'details.json'
    missing_resume = replace(series, season_id='', episode_id='', user_progress=None)
    first = process_items([missing_resume], client, DetailCache(path))[0]
    assert first.resume_episode == 'S3E1'
    assert client.fetch.call_count == client.fetch_episodes.call_count == 1
    entry = json.loads(path.read_text())[series.content_id]
    assert entry['resume_fallback'] == {
        'season_id': 'squirtle_s3', 'episode_id': 'squirtle_s3e1',
        'season_number': 3, 'episode_number': 1,
    }
    assert set(entry) == {'retrieved_at', 'availability_end_date', 'subgenre', 'resume_fallback'}
    assert 'https://' not in path.read_text()
    assert 'a' * 32 not in path.read_text()
    client.reset_mock()
    assert process_items([missing_resume], client, DetailCache(path))[0] == first
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()
    assert json.loads(path.read_text())[series.content_id]['retrieved_at'] == entry['retrieved_at']

    # Explicit playlist progression overrides the cached S3E1 fallback immediately.
    explicit = process_items([series], client, DetailCache(path))[0]
    assert explicit.resume_episode == 'S3E3'
    assert explicit.episodes_remaining == 9
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()

    action = client.fetch.return_value['actionLayout']['primaryActions'][0]
    action['onClick']['contentID'] = 'squirtle_s3e5'
    action['tracking']['dataLayer']['episodeNumber'] = 5
    refreshed = process_items([missing_resume], client, DetailCache(path), refresh=True)[0]
    assert refreshed.resume_episode == 'S3E5'
    assert refreshed.episodes_remaining == 7
    assert client.fetch.call_count == client.fetch_episodes.call_count == 1
    assert DetailCache(path).get(series.content_id).resume_fallback.episode_id == 'squirtle_s3e5'
    client.reset_mock()
    assert process_items([missing_resume], client, DetailCache(path))[0] == refreshed
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()


def test_fallback_uses_existing_detail_ttl(tmp_path, series, client):
    path = tmp_path / 'details.json'
    series = replace(series, season_id='', episode_id='')
    process_items([series], client, DetailCache(path))
    cache = DetailCache(path)
    cache.entries[series.content_id]['retrieved_at'] = (
        datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    client.reset_mock()
    process_items([series], client, cache)
    client.fetch.assert_called_once()
    client.fetch_episodes.assert_not_called()


@pytest.mark.parametrize('missing_duration', [False, True])
def test_expiration_partition_rows_cache_and_excel(
    tmp_path, series, client, fixture_data, missing_duration,
):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from mycanal_expiry_tracker.excel import COLUMNS, DAYS_FORMULA, write_excel

    template = fixture_data('episodes_series.json')
    catalogs = {n: season_response(template, n, ['21 min'] * 4, [3, 4, 5, 7])
                for n in (3, 4, 5, 7)}
    early = 1790801940000
    late = 1790805540000  # Same Paris date, distinct exact timestamps.
    for n, catalog in catalogs.items():
        for episode in catalog['episodes']['contents']:
            episode['availabilityEndDate'] = late if n in (4, 5) else early
    catalogs[3]['episodes']['contents'][3]['availabilityEndDate'] = late
    catalogs[7]['episodes']['contents'][-1]['availabilityEndDate'] = None
    catalogs[5]['episodes']['contents'][-1]['availabilityEndDate'] = 'invalid'
    if missing_duration:
        catalogs[7]['episodes']['contents'][0]['durationLabel'] = 'unknown'
    # Resolve S3E3 from detail, then exercise the cached fallback on the second run.
    series = replace(series, season_id='', episode_id='')
    action = client.fetch.return_value['actionLayout']['primaryActions'][0]
    action['onClick']['contentID'] = 'squirtle_s3e3'
    action['tracking']['dataLayer']['episodeNumber'] = 3

    def fetch(url, content_id):
        number = int(parse_qs(urlsplit(url).query)['seasonID'][0].removeprefix('squirtle_s'))
        return catalogs[number]

    client.fetch_episodes.side_effect = fetch
    path = tmp_path / 'details.json'
    results = process_items([series], client, DetailCache(path))
    assert len(results) == 3
    assert {r.resume_episode for r in results} == {'S3E3'}
    assert {r.item.title for r in results} == {'Squirtle'}
    groups = {r.availability_end_date: r for r in results}
    assert set(groups) == {early, late, None}
    assert [groups[t].episodes_remaining for t in (early, late, None)] == [4, 8, 2]
    assert [groups[t].season_numbers for t in (early, late, None)] == [(3, 7), (3, 4, 5), (5, 7)]
    assert groups[early].duration_minutes == (None if missing_duration else 84)
    assert groups[late].duration_minutes == 168
    assert groups[None].duration_minutes == 42
    assert sum(r.episodes_remaining for r in results) == 14
    if not missing_duration:
        assert sum(r.duration_minutes for r in results) == 294
    assert groups[None].expiration is None
    assert groups[None].availability_text == ''
    assert groups[None].status == 'Date inconnue'
    assert groups[early].expiration == groups[late].expiration == date(2026, 9, 30)
    assert client.fetch.call_count == 1
    assert client.fetch_episodes.call_count == 4
    saved = path.read_text()
    assert all(value not in saved for value in ('https://', 'Saisons', 'groups', 'episodes_remaining'))
    client.reset_mock()
    assert process_items([series], client, DetailCache(path)) == results
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()
    assert path.read_text() == saved
    assert process_items([series], client, DetailCache(path), refresh=True) == results
    assert client.fetch.call_count == 1
    assert client.fetch_episodes.call_count == 4

    output = tmp_path / 'groups.xlsx'
    frame = write_excel(list(reversed(results)), output, date(2026, 9, 29))
    assert frame.columns.tolist() == COLUMNS
    assert frame['Catégorie'].tolist() == ['Saisons 3, 7', 'Saisons 3 à 5', 'Saisons 5, 7']
    assert frame['Épisode à reprendre'].tolist() == ['S3E3'] * 3
    assert frame["Disponible jusqu'au"].iloc[:2].tolist() == [
        groups[early].availability_text, groups[late].availability_text,
    ]
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with ZipFile(output) as book:
        sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        table = ET.fromstring(book.read('xl/tables/table1.xml'))
        assert table.attrib['ref'] == 'A1:N4'
        assert sheet.find('m:conditionalFormatting', ns).attrib['sqref'] == 'A2:N4'
        assert all('ISNUMBER($D2)' in f.text for f in sheet.findall('.//m:cfRule/m:formula', ns))
        for row in range(2, 5):
            assert sheet.find(f'.//m:c[@r="D{row}"]/m:f', ns).text == DAYS_FORMULA[1:]
        assert sheet.find('.//m:c[@r="D4"]/m:v', ns).text is None
        assert sheet.find('.//m:c[@r="M4"]/m:v', ns) is None
        for row, minutes in ((2, None if missing_duration else 84), (3, 168), (4, 42)):
            cell = sheet.find(f'.//m:c[@r="H{row}"]', ns)
            if minutes is None:
                assert cell is None or cell.find('m:v', ns) is None
            else:
                assert cell.attrib.get('t', 'n') == 'n'
                assert float(cell.find('m:v', ns).text) == pytest.approx(minutes / 1440)


def test_playlist_completion_is_literal_boolean(tmp_path, fixture_data):
    template = fixture_data('playlist.json')['contents'][1]
    values = [True, False, None, 1, 'true', [], {}]
    contents = []
    for index, value in enumerate(values):
        raw = deepcopy(template)
        raw.update(contentID=f'completion_{index}', isCompleted=value, userProgress=98)
        contents.append(raw)
    missing = deepcopy(template)
    missing['contentID'] = 'completion_missing'
    missing.pop('isCompleted', None)
    contents.append(missing)
    (tmp_path / 'playlist.json').write_text(json.dumps({'contents': contents}))
    assert [item.is_completed for item in load_playlist(tmp_path)] == [True] + [False] * 7


def test_completion_changes_cached_groups_without_requests(tmp_path, series, client):
    contents = client.fetch_episodes.return_value['episodes']['contents']
    contents[2]['availabilityEndDate'] = 1790801940000
    contents.reverse()
    series = replace(series, is_completed=False, user_progress=98)
    path = tmp_path / 'details.json'
    first = process_items([series], client, DetailCache(path))
    assert sum(r.episodes_remaining for r in first) == 3
    assert sum(r.duration_minutes for r in first) == 63
    assert len(first) == 2
    saved = path.read_text()
    client.reset_mock()
    completed = process_items([replace(series, is_completed=True)], client, DetailCache(path))
    assert len(completed) == 1
    assert completed[0].episodes_remaining == 2
    assert completed[0].duration_minutes == 42
    assert completed[0].availability_end_date == 1788213540000
    assert completed[0].resume_episode == 'S3E2'
    assert path.read_text() == saved
    # The reversed Hodor sequence continues from E2 to E1, not numerically to E3.
    split = process_items(
        [replace(series, episode_id='squirtle_s3e2', is_completed=True)],
        client, DetailCache(path),
    )
    assert len(split) == 1
    assert {row.resume_episode for row in split} == {'S3E1'}
    assert 'is_completed' not in saved and 'isCompleted' not in saved
    assert process_items([series], client, DetailCache(path)) == first
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()


@pytest.mark.parametrize('later_season', [False, True])
def test_completed_final_episode_keeps_row_or_later_backlog(
    tmp_path, series, client, fixture_data, later_season,
):
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    from mycanal_expiry_tracker.excel import write_excel

    series = replace(series, episode_id='squirtle_s3e4', is_completed=True)
    template = fixture_data('episodes_series.json')
    seasons = [3, 5] if later_season else [3]
    current = season_response(template, 3, ['50 min'] * 4, seasons)
    current['episodes']['contents'][-1]['availabilityEndDate'] = 1790805540000
    client.fetch_episodes.side_effect = [current] + (
        [season_response(template, 5, ['21 min'] * 2, seasons)] if later_season else []
    )
    results = process_items([series], client, DetailCache(tmp_path / 'details.json'))
    assert len(results) == 1
    result = results[0]
    assert result.episodes_remaining == (2 if later_season else 0)
    assert result.duration_minutes == (42 if later_season else 0)
    assert result.resume_episode == ('S5E1' if later_season else '')
    assert result.availability_end_date == (1823119140000 if later_season else None)
    assert client.fetch_episodes.call_count == (2 if later_season else 1)
    if not later_season:
        assert result.expiration is None and result.availability_text == ''
        path = tmp_path / 'completed.xlsx'
        frame = write_excel(results, path)
        assert len(frame) == 1
        assert frame['Durée'].tolist() == [0]
        ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(path) as book:
            sheet = ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
            for ref in ('G2', 'H2'):
                cell = sheet.find(f'.//m:c[@r="{ref}"]', ns)
                assert cell.attrib.get('t', 'n') == 'n'
                assert float(cell.find('m:v', ns).text) == 0
            for ref in ('F2', 'M2'):
                assert sheet.find(f'.//m:c[@r="{ref}"]/m:v', ns) is None
            assert sheet.find('.//m:c[@r="D2"]/m:v', ns).text is None


def test_movie_completion_does_not_change_report(tmp_path, item, client, fixture_data):
    client.fetch.return_value = fixture_data('detail_movie_v5.json')
    cache = DetailCache(tmp_path / 'details.json')
    original = process_items([item], client, cache)[0]
    completed_item = replace(item, is_completed=True)
    completed = process_items([completed_item], client, cache)
    assert completed == [replace(original, item=completed_item)]


@pytest.mark.parametrize('completed,expected_label,expected_count', [
    (False, 'Mammouth', 3), (True, 'S3E2', 2),
])
def test_mixed_season_uses_editorial_order_and_preserves_cached_titles(
        tmp_path, series, client, completed, expected_label, expected_count):
    payload = season_response(client.fetch_episodes.return_value, 3, ['21 min'] * 4, [3])
    payload['episodes']['contents'] = [
        {'contentID': '900_50006', 'title': 'Before', 'durationLabel': '21 min'},
        {'contentID': '800_50006', 'title': 'Mammouth', 'durationLabel': '21 min'},
        {'contentID': 'normal_gptou', 'episodeNumber': 2, 'durationLabel': '21 min'},
        {'contentID': '100_50006', 'title': 'After', 'durationLabel': '21 min'},
    ]
    client.fetch_episodes.return_value = payload
    item = replace(series, episode_id='800_50006', is_completed=completed)
    path = tmp_path / 'details.json'
    first = process_items([item], client, DetailCache(path))[0]
    assert first.resume_episode == expected_label
    assert first.episodes_remaining == expected_count
    assert first.duration_minutes == expected_count * 21
    client.reset_mock()
    assert process_items([item], client, DetailCache(path))[0] == first
    client.fetch_episodes.assert_not_called()
    raw = json.loads(path.read_text())
    episodes = raw['season:squirtle_brand:squirtle_s3']['catalog']['episodes']
    assert [episode['content_id'] for episode in episodes] == [
        '900_50006', '800_50006', 'normal_gptou', '100_50006']
    assert episodes[1]['title'] == 'Mammouth'


def test_completed_resume_uses_first_editorial_unit_of_later_season(tmp_path, series, client):
    template = client.fetch_episodes.return_value
    current = season_response(template, 3, ['21 min'], [3, 5])
    later = season_response(template, 5, ['21 min', '21 min'], [3, 5])
    later['episodes']['contents'] = [
        {'contentID': '900_50006', 'title': 'First editorial unit', 'durationLabel': '21 min'},
        {'contentID': '100_50006', 'title': 'Second editorial unit', 'durationLabel': '21 min'}]
    client.fetch_episodes.side_effect = [current, later]
    item = replace(series, episode_id='squirtle_s3e1', is_completed=True)
    result = process_items([item], client, DetailCache(tmp_path / 'details.json'))[0]
    assert result.resume_episode == 'First editorial unit'
    assert result.episodes_remaining == 2


def test_synthetic_helper_and_legacy_title_fallback():
    from mycanal_hodor_core.episodes import Episode, Season, SeasonCatalog
    from mycanal_expiry_tracker.series import is_synthetic_episode_number, _episode_label
    from mycanal_expiry_tracker.catalog_cache import catalog_to_cache, catalog_from_cache
    synthetic = Episode('123_45', 12345, 21, None, 'Mammouth')
    assert is_synthetic_episode_number(synthetic)
    assert is_synthetic_episode_number(Episode('1_2', 12, 21, None))
    assert not is_synthetic_episode_number(Episode('123_45', 20000, 21, None))
    assert not is_synthetic_episode_number(Episode('invalid_id', 12345, 21, None))
    season = Season('season_mammouth', 1)
    raw = catalog_to_cache(SeasonCatalog(season, (season,), (synthetic,)))
    del raw['episodes'][0]['title']
    restored = catalog_from_cache(raw)
    assert restored.episodes[0].title is None
    assert _episode_label(1, restored.episodes[0]) == 'Unité non numérotée'


@pytest.mark.parametrize('resume_id,number,completed,count,label', [
    ('unit_a', 173, False, 4, 'S3E173'),
    ('unit_a', 173, True, 3, 'S3E174'),
    ('unit_b', 173, False, 2, 'S3E173'),
    ('unit_b', 173, True, 1, 'S3E82'),
    ('', 174, False, 3, 'S3E174'),
    ('', 173, False, None, None),
])
def test_editorial_numbers_describe_but_hodor_order_progresses(
        tmp_path, series, client, resume_id, number, completed, count, label):
    payload = season_response(client.fetch_episodes.return_value, 3, ['21 min'] * 4, [3])
    for entry, identity, value in zip(payload['episodes']['contents'],
                                      ['unit_a', 'unit_middle', 'unit_b', 'unit_last'],
                                      [173, 174, 173, 82]):
        entry.update(contentID=identity, episodeNumber=value)
    client.fetch_episodes.return_value = payload
    item = replace(series, episode_id=resume_id, episode_number=number, is_completed=completed)
    path = tmp_path / 'details.json'
    first = process_items([item], client, DetailCache(path))[0]
    if count is None:
        assert first.episodes_remaining is None
    else:
        assert first.episodes_remaining == count
        assert first.duration_minutes == count * 21
        assert first.resume_episode == label
    client.reset_mock()
    assert process_items([item], client, DetailCache(path))[0] == first
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()


@pytest.mark.parametrize('completed,expected_count,label', [
    (False, 2, 'Mammouth'), (True, 1, 'S0E2'),
])
def test_cached_s0_resume_preserves_editorial_order(tmp_path, series, client, completed, expected_count, label):
    from mycanal_hodor_core.episodes import Episode, Season, SeasonCatalog
    season = Season('squirtle_s0', 0)
    catalog = SeasonCatalog(season, (season,), (
        Episode('900_50006', 90050006, 21, 1790805540000, 'Mammouth'),
        Episode('unit_gptou', 2, 30, 1790805540000),
    ))
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    cache.put_season(series.content_id, catalog)
    cache.save()
    item = replace(series, season_id=season.content_id, season_number=0,
                   episode_id='900_50006', is_completed=completed)
    result = process_items([item], client, DetailCache(path))[0]
    assert result.season_numbers == (0,)
    assert result.resume_episode == label
    assert result.episodes_remaining == expected_count
    assert result.duration_minutes == (30 if completed else 51)
    assert result.availability_end_date == 1790805540000
    client.fetch_episodes.assert_not_called()


def test_partial_playlist_s0_is_not_replaced_by_fallback(tmp_path, series, client):
    from mycanal_expiry_tracker.detail import DetailData, ResumeFallback
    path = tmp_path / 'details.json'
    cache = DetailCache(path)
    cache.put(series.content_id, DetailData(resume_fallback=ResumeFallback(
        series.season_id, series.episode_id, 3, 3)))
    cache.save()
    # The cached fallback can fill the missing episode identity, but not replace S0.
    item = replace(series, season_number=0, episode_id='', episode_number=None)
    result = process_items([item], client, DetailCache(path))[0]
    assert result.episodes_remaining is None
    assert result.status != 'OK'


@pytest.mark.parametrize('identity,completed,duplicate,count,label', [
    ('pilot', False, False, 3, 'S1E0'),
    ('pilot', True, False, 2, 'S1E1'),
    ('', False, False, 3, 'S1E0'),
    ('', False, True, None, None),
    ('pilot', False, True, 3, 'S1E0'),
])
def test_real_zero_resume_and_cached_hodor_order(tmp_path, series, client, identity, completed, duplicate, count, label):
    from mycanal_hodor_core.episodes import Episode, Season, SeasonCatalog
    from mycanal_expiry_tracker.series import is_synthetic_episode_number
    season = Season('squirtle_s1', 1)
    episodes = (Episode('pilot', 0, 63, 1790805540000, 'The Pilot'),
                Episode('next', 1, 30, 1790805540000),
                Episode('last', 0 if duplicate else 2, 30, 1790805540000))
    assert not is_synthetic_episode_number(episodes[0])
    assert not is_synthetic_episode_number(Episode('0_0', 0, 63, None))
    path = tmp_path/'details.json'
    cache = DetailCache(path)
    cache.put_season(series.content_id, SeasonCatalog(season,(season,),episodes))
    cache.save()
    assert DetailCache(path).get_season(series.content_id, season.content_id).episodes == episodes
    item = replace(series, season_id=season.content_id, season_number=1,
                   episode_id=identity, episode_number=0, is_completed=completed)
    result = process_items([item], client, DetailCache(path))[0]
    assert result.episodes_remaining == count
    if count is not None:
        assert result.resume_episode == label
        assert result.duration_minutes == (60 if completed else 123)
    client.fetch.assert_not_called()
    client.fetch_episodes.assert_not_called()
