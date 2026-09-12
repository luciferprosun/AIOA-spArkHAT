from urllib.parse import parse_qs, urlsplit

import pytest
from scripts.run_local_hitl_api import _browser_bootstrap_url


def test_browser_bootstrap_keeps_session_credential_in_fragment_only() -> None:
    token = "portable-judge-token-" + "t" * 32

    url = _browser_bootstrap_url("127.0.0.1", 8765, token)
    parsed = urlsplit(url)

    assert parsed.scheme == "http"
    assert parsed.netloc == "127.0.0.1:8765"
    assert parsed.path == "/"
    assert parsed.query == ""
    assert parse_qs(parsed.fragment) == {"access_token": [token]}


@pytest.mark.parametrize(("host", "port"), [("0.0.0.0", 8765), ("127.0.0.1", -1)])
def test_browser_bootstrap_rejects_non_loopback_or_invalid_port(
    host: str,
    port: int,
) -> None:
    with pytest.raises(ValueError, match="loopback"):
        _browser_bootstrap_url(host, port, "t" * 48)
