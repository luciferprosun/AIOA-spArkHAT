"""Pytest plugin that fails B4 proof processes on non-loopback socket egress."""

from __future__ import annotations

import ipaddress
import socket
from typing import Final

_ORIGINAL_CONNECT: Final = socket.socket.connect
_ORIGINAL_CONNECT_EX: Final = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION: Final = socket.create_connection
_ORIGINAL_SENDTO: Final = socket.socket.sendto
_INSTALLED = False


def _is_loopback(address: object) -> bool:
    if isinstance(address, str):
        return True  # AF_UNIX filesystem/abstract socket, never external egress.
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if not isinstance(host, str):
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _require_loopback(address: object) -> None:
    if not _is_loopback(address):
        raise AssertionError("B4_UNEXPECTED_EXTERNAL_NETWORK_EGRESS")


def _guarded_connect(instance: socket.socket, address: object) -> None:
    _require_loopback(address)
    _ORIGINAL_CONNECT(instance, address)  # type: ignore[arg-type]


def _guarded_connect_ex(instance: socket.socket, address: object) -> int:
    _require_loopback(address)
    return _ORIGINAL_CONNECT_EX(instance, address)  # type: ignore[arg-type]


def _guarded_create_connection(
    address: object,
    timeout: object = socket._GLOBAL_DEFAULT_TIMEOUT,
    source_address: object = None,
    *,
    all_errors: bool = False,
) -> socket.socket:
    _require_loopback(address)
    return _ORIGINAL_CREATE_CONNECTION(
        address,  # type: ignore[arg-type]
        timeout,  # type: ignore[arg-type]
        source_address,  # type: ignore[arg-type]
        all_errors=all_errors,
    )


def _guarded_sendto(instance: socket.socket, data: bytes, *args: object) -> int:
    if not args:
        raise AssertionError("B4_UNEXPECTED_EXTERNAL_NETWORK_EGRESS")
    _require_loopback(args[-1])
    return _ORIGINAL_SENDTO(instance, data, *args)  # type: ignore[arg-type]


def pytest_configure() -> None:
    """Install the process-local guard before test collection executes imports."""

    global _INSTALLED
    if _INSTALLED:
        return
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.create_connection = _guarded_create_connection
    socket.socket.sendto = _guarded_sendto
    _INSTALLED = True


def pytest_unconfigure() -> None:
    """Restore socket functions for embedding test runners in a longer-lived process."""

    global _INSTALLED
    if not _INSTALLED:
        return
    socket.socket.connect = _ORIGINAL_CONNECT
    socket.socket.connect_ex = _ORIGINAL_CONNECT_EX
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION
    socket.socket.sendto = _ORIGINAL_SENDTO
    _INSTALLED = False
