"""FinAgent test fixtures.

Overrides the suite-wide ``_no_network`` guard for this package so that loopback
connections stay allowed: asyncio's event loop on Windows builds its self-pipe
from a loopback socket pair, and integration tests talk to the docker-compose
Postgres and Redis on localhost. Everything else still refuses the network.
"""

from __future__ import annotations

import socket

import pytest

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        return
    real_connect, real_connect_ex, real_getaddrinfo = socket.socket.connect, socket.socket.connect_ex, \
        socket.getaddrinfo

    def _host(address):
        return address[0] if isinstance(address, tuple) else address

    def connect(self, address):
        if _host(address) in _LOOPBACK:
            return real_connect(self, address)
        raise OSError(f"test tried to reach the network: {address}")

    def connect_ex(self, address):
        if _host(address) in _LOOPBACK:
            return real_connect_ex(self, address)
        raise OSError(f"test tried to reach the network: {address}")

    def getaddrinfo(host, *args, **kwargs):
        if host in _LOOPBACK or host is None:
            return real_getaddrinfo(host, *args, **kwargs)
        raise OSError(f"test tried to reach the network: {host}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    from curl_cffi import requests as curl_requests

    def refuse(*args, **kwargs):
        raise OSError("test tried to reach the network (curl)")

    monkeypatch.setattr(curl_requests.Session, "request", refuse)
    monkeypatch.setattr(curl_requests.AsyncSession, "request", refuse)
