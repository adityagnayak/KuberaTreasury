"""
NexusTreasury — RBAC (Role-Based Access Control) Service (Phase 5)
"""

from __future__ import annotations

from typing import Dict, Set

from app.core.exceptions import PermissionDeniedError

# ─── Permission matrix ────────────────────────────────────────────────────────

ROLE_PERMISSIONS: Dict[str, Dict[str, Set[str]]] = {
    "treasury_analyst": {
        "allow": {
            "READ:transactions",
            "READ:cash_positions",
            "READ:forecasts",
            "WRITE:forecasts",
            "WRITE:initiate_payment",
        },
        "deny": {
            "WRITE:approve_payment",
            "READ:audit_logs",
            "READ:mandates",
            "WRITE:mandates",
            "DELETE:*",
        },
    },
    "treasury_manager": {
        "allow": {
            "READ:transactions",
            "READ:cash_positions",
            "READ:forecasts",
            "WRITE:forecasts",
            "WRITE:initiate_payment",
            "WRITE:approve_payment",
            "READ:audit_logs",
            "READ:mandates",
            "WRITE:mandates",
        },
        "deny": {
            "DELETE:*",
            "WRITE:system_config",
        },
    },
    "auditor": {
        "allow": {
            "READ:transactions",
            "READ:cash_positions",
            "READ:forecasts",
            "READ:audit_logs",
            "READ:mandates",
            "READ:payments",
        },
        "deny": {
            "WRITE:*",
            "DELETE:*",
        },
    },
    "system_admin": {
        "allow": {
            "READ:*",
            "WRITE:*",
            "WRITE:system_config",
            "WRITE:mandates",
        },
        "deny": set(),
    },
}


def _permission_key(action: str, resource: str) -> str:
    return f"{action}:{resource}"


class RBACService:
    """Checks whether a given role is permitted to perform an action on a resource."""

    def check(self, role: str, action: str, resource: str, user_id: str = "") -> bool:
        """
        Return True if the role is allowed.
        Raise PermissionDeniedError otherwise.

        Priority: explicit deny > explicit allow > default deny.
        Wildcard '*' is supported on both action and resource side of deny rules.
        """
        perms = ROLE_PERMISSIONS.get(role)
        if perms is None:
            raise PermissionDeniedError(role, action, resource)

        key = _permission_key(action, resource)
        deny_set = perms.get("deny", set())
        allow_set = perms.get("allow", set())

        # Check deny rules (wildcards)
        for deny_key in deny_set:
            deny_action, deny_resource = deny_key.split(":", 1)
            if (deny_action in (action, "*") and deny_resource in (resource, "*")):
                raise PermissionDeniedError(role, action, resource)

        # Check explicit allow
        for allow_key in allow_set:
            allow_action, allow_resource = allow_key.split(":", 1)
            if (allow_action in (action, "*") and allow_resource in (resource, "*")):
                return True

        # Default deny
        raise PermissionDeniedError(role, action, resource)

    def has_permission(self, role: str, action: str, resource: str) -> bool:
        """Non-raising version of check(). Returns True/False."""
        try:
            return self.check(role, action, resource)
        except PermissionDeniedError:
            return False
