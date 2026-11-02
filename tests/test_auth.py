import os

import pytest

from app.auth import AdminAuth, LoginThrottle, hash_password, load_or_create_secret

PASSWORD = "un-mot-de-passe-solide"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def pw_hash():
    return hash_password(PASSWORD)


def make_auth(pw_hash, clock=None, secret=b"s" * 32):
    return AdminAuth("greg", pw_hash, secret, max_age=3600, clock=clock or Clock())


def test_verify_password(pw_hash):
    auth = make_auth(pw_hash)
    assert auth.verify_password("greg", PASSWORD)
    assert not auth.verify_password("greg", "faux")
    assert not auth.verify_password("autre", PASSWORD)


def test_disabled_without_hash():
    auth = AdminAuth("greg", "", b"s" * 32)
    assert not auth.enabled
    assert not auth.verify_password("greg", "")
    assert not auth.check_session("123.abc")


def test_invalid_hash_does_not_crash():
    assert not AdminAuth("greg", "pas-un-hash", b"s" * 32).verify_password("greg", "x")


def test_session_roundtrip_and_expiry(pw_hash):
    clock = Clock()
    auth = make_auth(pw_hash, clock)
    value = auth.make_session()
    assert auth.check_session(value)
    clock.t += 3601
    assert not auth.check_session(value)


@pytest.mark.parametrize("value", [None, "", "abc", "9999999999.", "9999999999.deadbeef", "x.y"])
def test_forged_sessions_are_rejected(pw_hash, value):
    assert not make_auth(pw_hash).check_session(value)


def test_session_tied_to_secret_and_password(pw_hash):
    value = make_auth(pw_hash).make_session()
    assert not make_auth(pw_hash, secret=b"t" * 32).check_session(value)
    assert not make_auth(hash_password("nouveau-mot-de-passe")).check_session(value)


def test_throttle_blocks_then_releases():
    clock = Clock(0.0)
    t = LoginThrottle(max_failures=3, window_s=60, clock=clock)
    for _ in range(3):
        assert t.retry_after("ip") == 0
        t.failure("ip")
    assert t.retry_after("ip") > 0
    assert t.retry_after("autre-ip") == 0
    clock.t = 61
    assert t.retry_after("ip") == 0


def test_throttle_reset_on_success():
    t = LoginThrottle(max_failures=2, window_s=60, clock=Clock(0.0))
    t.failure("ip")
    t.success("ip")
    t.failure("ip")
    assert t.retry_after("ip") == 0


def test_secret_is_created_once_and_private(tmp_path):
    path = tmp_path / "data" / "session_secret"
    first = load_or_create_secret(path)
    assert len(first) == 32
    assert load_or_create_secret(path) == first
    if os.name == "posix":
        assert oct(path.stat().st_mode & 0o777) == "0o600"
