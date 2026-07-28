"""Deny-by-default privacy checks and public-export tooling.

The public names are loaded lazily so ``python -m hfmd.privacy.audit`` can run
without importing its target module twice.
"""

from typing import Any

__all__ = ["AuditFinding", "AuditResult", "PrivacyPolicy", "audit_tree"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from . import audit

        return getattr(audit, name)
    raise AttributeError(name)
