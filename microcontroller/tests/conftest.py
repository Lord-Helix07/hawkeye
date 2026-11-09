"""Bounded mocks for Alvina's launch and landing sequences.

Real serial devices, vehicle connections, operator stdin, sleeps, and
network calls are refused. Clocks advance only when a test or a mock
read moves them.
"""

import socket
import sys
import urllib.request
from pathlib import Path

import pytest

MICROCONTROLLER_DIR = Path(__file__).resolve().parents[1]
if str(MICROCONTROLLER_DIR) not in sys.path:
    sys.path.insert(0, str(MICROCONTROLLER_DIR))

import landing_sequence  # noqa: E402
import launch_handshake  # noqa: E402
import launch_sequence  # noqa: E402


class Clock:
    def __init__(self, start=1000.0):
        self.now = float(start)

    def monotonic(self):
        return self.now

    def advance(self, seconds):
        self.now += float(seconds)


class HttpLog:
    def __init__(self):
        self.calls = []

    def urlopen(self, url, *args, **kwargs):
        self.calls.append(url)
        raise AssertionError(
            f"HTTP is mocked; refusing {url!r}"
        )


def _refuse_network(*args, **kwargs):
    raise AssertionError("real network access is blocked")


def _refuse_input(*args, **kwargs):
    raise AssertionError("real operator input is blocked")


def _refuse_sleep(seconds=0):
    raise AssertionError(f"real sleep is blocked ({seconds})")


def _refuse_vehicle_connection(*args, **kwargs):
    raise AssertionError(
        "real vehicle connection is blocked; tests must pass a mock"
    )


@pytest.fixture(autouse=True)
def block_hardware_and_network(monkeypatch):
    http = HttpLog()
    monkeypatch.setattr(socket.socket, "connect", _refuse_network)
    monkeypatch.setattr(socket, "create_connection", _refuse_network)
    monkeypatch.setattr(urllib.request, "urlopen", http.urlopen)
    monkeypatch.setattr("builtins.input", _refuse_input)
    monkeypatch.setattr(launch_sequence.time, "sleep", _refuse_sleep)
    monkeypatch.setattr(landing_sequence.time, "sleep", _refuse_sleep)
    monkeypatch.setattr(
        launch_sequence.mavutil,
        "mavlink_connection",
        _refuse_vehicle_connection,
    )
    if hasattr(landing_sequence, "mavutil"):
        monkeypatch.setattr(
            landing_sequence.mavutil,
            "mavlink_connection",
            _refuse_vehicle_connection,
        )
    return http


@pytest.fixture(autouse=True)
def stop_backend_worker():
    yield
    import backend_comms

    backend_comms.stop_worker()


@pytest.fixture
def clock(monkeypatch):
    virtual = Clock()
    import fc_status
    import health_monitor
    import main as flight_main
    from flight_controller import fc_connection
    from flight_controller import fc_utils

    for module in (
        launch_sequence,
        launch_handshake,
        landing_sequence,
        flight_main,
        health_monitor,
        fc_status,
        fc_connection,
        fc_utils,
    ):
        if hasattr(module, "time"):
            monkeypatch.setattr(module.time, "monotonic", virtual.monotonic)
    return virtual


@pytest.fixture
def operator(monkeypatch):
    holder = {"response": "CONFIRM"}
    if not hasattr(launch_sequence, "OperatorInput"):
        return holder

    class ScriptedOperator:
        def __init__(self):
            pass

        def get_response(self):
            return holder["response"]

    monkeypatch.setattr(
        launch_sequence, "OperatorInput", ScriptedOperator
    )
    return holder
