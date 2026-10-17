"""Authoritative challenge content package.

Challenge definitions, reference solutions, hidden tests, and impostor-only
objectives belong on the trusted backend side. Do not import or expose private
content through player-facing API responses. Player code must be executed only
by the isolated runner, never by the FastAPI process.

This package initializer intentionally has no imports or runtime side effects.
"""
