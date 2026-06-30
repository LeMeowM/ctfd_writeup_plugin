def test_plugin_loads(app):
    # The plugin registered its blueprint under the name "writeups".
    assert "writeups" in app.blueprints

def test_factories(make_admin, make_challenge):
    admin = make_admin()
    chal = make_challenge(name="rsa")
    assert admin.type == "admin"
    assert chal.id is not None
