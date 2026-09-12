"""Compatibility launcher for the packaged AWS-free portable judge command."""

from __future__ import annotations

from aioa_cloudops_agent.portable.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
