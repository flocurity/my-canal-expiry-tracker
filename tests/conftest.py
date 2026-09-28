import json
from pathlib import Path

import pytest
import requests

from src.playlist import PlaylistItem

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def block_network(request, monkeypatch):
    if request.node.get_closest_marker('integration') is None:
        def blocked(*args, **kwargs):
            raise AssertionError('Normal tests must not make network requests')
        monkeypatch.setattr(requests.sessions.Session, 'request', blocked)


@pytest.fixture
def fixture_data():
    def load(name):
        return json.loads((FIXTURES / name).read_text(encoding='utf-8'))
    return load


@pytest.fixture
def item():
    return PlaylistItem('fiction_50001', 'The Last Compiler', 'Film Science-fiction',
                        'VoD', 'CANAL+', True, '/cinema/the-last-compiler/h/fiction_50001',
                        'https://hodor.canalplus.pro/api/v2/mycanal/detail/fiction/okapi/'
                        'fiction_50001.json?detailType=detailPage&objectType=unit')
