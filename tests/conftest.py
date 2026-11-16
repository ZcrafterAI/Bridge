import webbrowser

import pytest


@pytest.fixture(autouse=True)
def no_real_browser(monkeypatch):
    """A test must never open a page on the machine it runs on. The addresses it would have
    opened are kept, so a test can act as the person and visit one."""
    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *args, **kwargs: opened.append(url) or True)
    return opened
