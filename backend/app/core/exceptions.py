"""Domain exceptions — converted to HTTP responses in middleware."""

from __future__ import annotations


class KuberaError(Exception):
    """Base error."""

    status_code: int = 500
    detail: str = "Internal error"


class UnbalancedJournalError(KuberaError):
    status_code = 422

    def __init__(self, debit_total: str, credit_total: str) -> None:
        self.detail = (
            f"Journal is unbalanced: total debits {debit_total} ≠ total credits {credit_total}. "
            "Every journal must satisfy Σ debits = Σ credits."
        )
        super().__init__(self.detail)


class PeriodClosedError(KuberaError):
    status_code = 409

    def __init__(self, period_name: str) -> None:
        self.detail = f"Period '{period_name}' is closed. Reverse to an open period or reopen the period first."
        super().__init__(self.detail)


class NotFoundError(KuberaError):
    status_code = 404

    def __init__(self, resource: str, id_: object) -> None:
        self.detail = f"{resource} '{id_}' not found."
        super().__init__(self.detail)


class PermissionDeniedError(KuberaError):
    status_code = 403

    def __init__(self, action: str) -> None:
        self.detail = f"Permission denied: {action}."
        super().__init__(self.detail)


class TransferPricingError(KuberaError):
    status_code = 422

    def __init__(self, variance_bps: float) -> None:
        self.detail = (
            f"Transfer pricing out of arm's-length range: variance {variance_bps:.1f}bps "
            "(allowed ±150bps). Add or update justification."
        )
        super().__init__(self.detail)


class HedgeEffectivenessError(KuberaError):
    status_code = 422

    def __init__(self, ratio: float) -> None:
        self.detail = (
            f"Hedge retrospective effectiveness {ratio:.1%} is outside the 80–125% qualifying range (IFRS 9 §B6.4.4). "
            "Hedge accounting must be discontinued."
        )
        super().__init__(self.detail)
