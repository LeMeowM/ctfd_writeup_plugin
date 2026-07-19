SCRIPT_URL = "/plugins/ctfd_censored_writeups/assets/challenge-tab.js"


def test_challenge_tab_script_registered(app):
    # register_plugin_script() appends to app.plugin_scripts, which base.html
    # renders into every page via {{ Plugins.scripts }}.
    with app.app_context():
        from CTFd.utils.plugins import get_registered_scripts
        assert SCRIPT_URL in get_registered_scripts()


def test_challenge_tab_script_in_page_html(app):
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert SCRIPT_URL.encode() in r.data


def test_challenge_tab_asset_served(app):
    client = app.test_client()
    r = client.get(SCRIPT_URL)
    assert r.status_code == 200
    # sanity: it is our script, not an error page
    assert b"challenge-window" in r.data
