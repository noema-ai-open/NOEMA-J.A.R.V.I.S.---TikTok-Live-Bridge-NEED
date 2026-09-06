from app.desktop import dashboard_url
from app.settings import BridgeSettings


def test_dashboard_url_uses_loopback_for_wildcard_host() -> None:
    assert dashboard_url(BridgeSettings(host="0.0.0.0", port=8770)) == (
        "http://127.0.0.1:8770"
    )


def test_dashboard_url_keeps_explicit_host() -> None:
    assert dashboard_url(BridgeSettings(host="127.0.0.1", port=9000)) == (
        "http://127.0.0.1:9000"
    )
