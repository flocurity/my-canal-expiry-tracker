from unittest.mock import MagicMock, Mock

import pytest

from tools.test_rate_limit import main


@pytest.mark.parametrize('status', [429, 403])
def test_observation_stops_on_rejection(monkeypatch, item, status):
    response = MagicMock(status_code=status, headers={'Retry-After': '60'})
    session = MagicMock()
    session.__enter__.return_value = session
    session.get.return_value = response
    monkeypatch.setattr('tools.test_rate_limit.requests.Session', lambda: session)
    sleep = Mock()
    monkeypatch.setattr('tools.test_rate_limit.time.sleep', sleep)
    assert main(['--url', item.detail_url, '--count', '20']) == 0
    session.get.assert_called_once()
    sleep.assert_not_called()


@pytest.mark.parametrize('args', [['--count', '21'], ['--count', '0'], ['--delay', '.1']])
def test_observation_rejects_aggressive_parameters(item, args):
    with pytest.raises(SystemExit) as error:
        main(['--url', item.detail_url, *args])
    assert error.value.code == 2
