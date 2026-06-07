import gigaflow.cli as cli


def test_user_token_preferred_over_config_key():
    resolved = cli._resolve_credential(
        flag=None, env_key=None, user_token="USER_JWT", config_key="STATIC"
    )
    assert resolved == "USER_JWT"


def test_explicit_flag_wins():
    resolved = cli._resolve_credential(
        flag="FLAG", env_key="ENV", user_token="USER_JWT", config_key="STATIC"
    )
    assert resolved == "FLAG"


def test_env_overrides_user_token():
    # An explicitly-set env key is treated as an override (CI/self-host intent).
    resolved = cli._resolve_credential(
        flag=None, env_key="ENV", user_token="USER_JWT", config_key="STATIC"
    )
    assert resolved == "ENV"


def test_falls_back_to_static_when_logged_out():
    resolved = cli._resolve_credential(
        flag=None, env_key=None, user_token=None, config_key="STATIC"
    )
    assert resolved == "STATIC"


def test_none_when_nothing_available():
    assert cli._resolve_credential(flag=None, env_key=None, user_token=None, config_key=None) is None


def test_backend_defaults_to_hosted_when_nothing_set():
    assert cli._resolve_backend_url(None, None, None) == "https://api.gigaflow.io/api/v1"


def test_backend_flag_wins_over_env_and_config():
    assert cli._resolve_backend_url("http://flag/api/v1", "http://env/api/v1", "http://cfg/api/v1") == "http://flag/api/v1"


def test_backend_env_over_config():
    assert cli._resolve_backend_url(None, "http://env/api/v1", "http://cfg/api/v1") == "http://env/api/v1"


def test_backend_config_over_default():
    assert cli._resolve_backend_url(None, None, "http://localhost:8000/api/v1") == "http://localhost:8000/api/v1"


def test_backend_trailing_slash_stripped():
    assert cli._resolve_backend_url("https://x/api/v1/", None, None) == "https://x/api/v1"
