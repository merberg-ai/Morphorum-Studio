"""The shared backend session: identity epochs, state and short-lived clients."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fakes import info
from PySide6.QtWidgets import QApplication

from morphorum_studio.backend.session import BackendSession


def _session():
    QApplication.instance() or QApplication(["morphorum-studio-tests"])
    made = []

    def factory(url, token, timeout=6.0):
        made.append((url, token, timeout))
        return object()

    return BackendSession(client_factory=factory), made


def test_starts_offline_with_no_client():
    session, _ = _session()
    assert session.state == "offline" and session.info is None and session.client() is None
    assert not session.feature("gpu_telemetry")


def test_connect_builds_clients_with_the_token_and_epoch_tracks_identity():
    session, made = _session()
    changes = []
    session.changed.connect(lambda: changes.append(session.state))
    session.connected(info(), "secret")
    first = session.epoch
    assert session.state == "connected" and session.client(timeout=3.0) is not None
    assert made == [("http://127.0.0.1:7866", "secret", 3.0)]
    assert session.feature("gpu_telemetry") and not session.feature("nonexistent")

    session.connected(info(), "secret")  # identical health probe: nothing to announce
    assert changes == ["connected"] and session.epoch == first

    session.connected(info(boot="c"), "secret")  # backend restarted
    assert session.epoch == first + 1 and changes == ["connected", "connected"]
    session.connected(info(boot="c", instance="d"), "secret")  # a different installation
    assert session.epoch == first + 2
    session.connected(info(boot="c", instance="d", profile="p2"), "secret")  # another profile
    assert session.epoch == first + 3


def test_outage_keeps_the_epoch_and_recovery_resumes_it():
    session, _ = _session()
    session.connected(info(), "t")
    epoch = session.epoch
    session.reconnecting()
    assert session.state == "reconnecting" and session.client() is None and session.info is not None
    session.connected(info(), "t")
    assert session.state == "connected" and session.epoch == epoch


def test_disconnect_forgets_everything_and_invalidates_the_epoch():
    session, _ = _session()
    session.connected(info(), "secret")
    epoch = session.epoch
    changes = []
    session.changed.connect(lambda: changes.append(1))
    session.disconnected()
    assert (session.state, session.info, session.client()) == ("offline", None, None)
    assert session.epoch == epoch + 1 and session._token is None
    session.disconnected()  # idempotent
    session.reconnecting()  # nothing to reconnect to
    assert changes == [1] and session.state == "offline"
