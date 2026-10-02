import json
from dataclasses import replace

import pytest

from src.playlist import PlaylistError, load_playlist


def test_load_merge_deduplicate_optional_fields(tmp_path, fixture_data):
    data = fixture_data('playlist.json')
    data['contents'][1].pop('isInOffer')
    first = tmp_path / 'a.json'
    first.write_text(json.dumps(data), encoding='utf-8')
    (tmp_path / 'b.json').write_text(json.dumps(data), encoding='utf-8')
    before = first.read_bytes()
    items = load_playlist(tmp_path)
    assert len(items) == 2
    assert items[0].content_id == 'fiction_50001'
    assert items[0].subtitle == 'Film Science-fiction'
    assert items[0].service == 'CANAL+'
    assert items[0].in_offer is True
    assert items[1].in_offer is None
    assert items[1].content_type == 'folder'
    assert first.read_bytes() == before


@pytest.mark.parametrize('invalid', ['{bad', '[]', '{}', '{"contents": null}', '{"contents": {}}'])
def test_invalid_file_fails_even_with_valid_page(tmp_path, invalid):
    (tmp_path / 'good.json').write_text('{"contents": []}')
    (tmp_path / 'bad.json').write_text(invalid)
    with pytest.raises(PlaylistError, match='bad.json'):
        load_playlist(tmp_path)


def test_reports_all_invalid_files(tmp_path):
    (tmp_path / 'a.json').write_text('no')
    (tmp_path / 'b.json').write_text('no')
    with pytest.raises(PlaylistError) as error:
        load_playlist(tmp_path)
    assert 'a.json' in str(error.value) and 'b.json' in str(error.value)


def test_missing_input(tmp_path):
    with pytest.raises(PlaylistError, match='No .json'):
        load_playlist(tmp_path)


def test_empty_playlist(tmp_path):
    (tmp_path / 'a.json').write_text('{"contents": []}')
    assert load_playlist(tmp_path) == []


def test_skip_unusable_entries_keep_missing_ids(tmp_path, fixture_data):
    valid = fixture_data('playlist.json')['contents'][0]
    del valid['contentID']
    values = [None, [], {}, {'onClick': {'URLPage': 42}}, valid, valid]
    (tmp_path / 'a.json').write_text(json.dumps({'contents': values}))
    items = load_playlist(tmp_path)
    assert len(items) == 2
    assert all(item.content_id == '' for item in items)


def test_web_url(item):
    assert item.web_url == 'https://www.canalplus.com' + item.path
    for path in ('//evil.example/x', '/\\evil.example', 'javascript:alert(1)', ''):
        assert replace(item, path=path).web_url == item.detail_url
    assert replace(item, path='', detail_url='javascript:alert(1)').web_url == ''


def test_detail_v5_declaration_preserves_source_url(tmp_path, fixture_data):
    data = fixture_data('playlist.json')
    (tmp_path / 'page.json').write_text(json.dumps(data))
    movie, season = load_playlist(tmp_path)
    assert movie.supports_detail_v5 is True
    assert season.supports_detail_v5 is True
    assert season.detail_url == data['contents'][1]['onClick']['URLPage']
    assert season.season_id == 'fiction_season_50002'
    assert season.episode_id == 'fiction_episode_50002'
    assert season.is_completed is False
    assert season.user_progress == 64


@pytest.mark.parametrize('parameters', [
    None, {}, 'detailV5', [], [None, 42, 'detailV5'],
    [{'in': 'headers', 'id': 'featureToggles', 'enum': ['detailV5']}],
    [{'in': 'parameters', 'id': 'other', 'enum': ['detailV5']}],
    *[{'in': 'parameters', 'id': 'featureToggles', 'enum': value}
      for value in (None, 'detailV5', {'detailV5': True})],
    *[[{'in': 'parameters', 'id': 'featureToggles', 'enum': value}]
      for value in (None, 'detailV5', {}, [], ['detailV5Sport'], ['detailV5', None])],
])
def test_invalid_or_unsupported_parameters(tmp_path, fixture_data, parameters):
    data = fixture_data('playlist.json')
    raw = data['contents'][0]
    raw['onClick']['parameters'] = parameters
    (tmp_path / 'page.json').write_text(json.dumps({'contents': [raw]}))
    item = load_playlist(tmp_path)[0]
    assert item.supports_detail_v5 is False
    assert item.detail_url == raw['onClick']['URLPage']


@pytest.mark.parametrize('duration, expected', [(5880000, 5880000), (None, None),
                                               (True, None), ('5880000', None),
                                               (-1, None), (0, None), (1.5, None)])
def test_playlist_duration_milliseconds(tmp_path, fixture_data, duration, expected):
    data = fixture_data('playlist.json')
    data['contents'][0]['duration'] = duration
    (tmp_path / 'page.json').write_text(json.dumps(data))
    assert load_playlist(tmp_path)[0].duration_ms == expected
