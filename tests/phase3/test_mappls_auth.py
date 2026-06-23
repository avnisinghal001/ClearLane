from clearlane.phase3 import mappls_auth as auth


def _cfg():
    return {
        "mappls": {
            "authentication": {
                "rest_key_env": "MAPPLS_REST_KEY",
                "client_id_env": "MAPPLS_CLIENT_ID",
                "client_secret_env": "MAPPLS_CLIENT_SECRET",
                "access_token_env": "MAPPLS_ACCESS_TOKEN",
            }
        }
    }


def test_valid_static_key():
    creds = auth.load_credentials(_cfg(), env={"MAPPLS_REST_KEY": "abc123"})
    assert creds.has_rest_key
    assert creds.require_rest_key() == "abc123"


def test_missing_key_raises():
    creds = auth.load_credentials(_cfg(), env={})
    assert not creds.has_rest_key
    try:
        creds.require_rest_key()
        assert False
    except auth.AuthError as e:
        assert "MISSING" in str(e)


def test_oauth_optional():
    creds = auth.load_credentials(_cfg(), env={"MAPPLS_CLIENT_ID": "x", "MAPPLS_CLIENT_SECRET": "y"})
    assert creds.has_oauth


def test_status_report_has_no_values():
    creds = auth.load_credentials(_cfg(), env={"MAPPLS_REST_KEY": "supersecret", "MAPPLS_CLIENT_ID": "idval"})
    report = creds.status_report()
    text = str(report)
    assert "supersecret" not in text
    assert "idval" not in text
    assert report["rest_key_present"] is True
