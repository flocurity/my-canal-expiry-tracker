import json
from unittest.mock import Mock

import pytest

from mycanal_expiry_tracker import cli as main


def test_invalid_input_prevents_api_and_output(tmp_path, monkeypatch):
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input' / 'bad.json').write_text('invalid')
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    client = Mock()
    monkeypatch.setattr(main, 'CanalClient', client)
    assert main.main([]) == 1
    client.assert_not_called()
    assert not (tmp_path / 'output').exists()
    assert not (tmp_path / 'cache').exists()


def test_end_to_end_mocked(tmp_path, monkeypatch, fixture_data):
    (tmp_path / 'input').mkdir()
    playlist = fixture_data('playlist.json')
    playlist['contents'][1].update(seasonID='squirtle_s3', episodeID='squirtle_s3e3')
    (tmp_path / 'input' / 'page.json').write_text(json.dumps(playlist))
    monkeypatch.setattr(main, 'ROOT', tmp_path)
    client = Mock()
    client.fetch.side_effect = lambda url, content_id: fixture_data(
        'detail_movie.json' if content_id == 'fiction_50001' else 'detail_series_v5.json'
    )
    client.fetch_episodes.return_value = fixture_data('episodes_series.json')
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(main, 'CanalClient', Mock(return_value=context))
    assert main.main([]) == 0
    assert (tmp_path / 'output' / 'ma-liste-canal.xlsx').exists()
    assert (tmp_path / 'cache' / 'details.json').exists()
    assert client.fetch.call_count == 2
    assert client.fetch_episodes.call_count == 1
    assert main.main([]) == 0
    assert client.fetch.call_count == 2
    assert client.fetch_episodes.call_count == 1
    assert main.main(['--refresh', '--delay', '0.5']) == 0
    assert client.fetch.call_count == 4
    assert client.fetch_episodes.call_count == 2


@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'bad'])
def test_bad_delay(value):
    with pytest.raises(SystemExit) as error:
        main.main(['--delay', value])
    assert error.value.code == 2
