"""Trusted orchestration between game rules and the isolated code runner.

This package may prepare and validate jobs, but it never executes player Python.
Only the separately isolated runner service may execute submitted source.
"""
