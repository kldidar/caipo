"""The authentication context: who is acting, and how strongly they proved it (ADR-0014).

A context is a plain value, passed explicitly from the caller to the service
and from the service to the authorization decision. There is no ambient
"current user" and no flag kept in a global or a thread.

A context states a claim; it does not prove one. The decision in
`caipo.accounts.selectors` checks a claim of MFA_VERIFIED against the database
before it counts.
"""

from dataclasses import dataclass

from caipo.accounts.authorization import Assurance
from caipo.accounts.models import User


@dataclass(frozen=True)
class AuthenticationContext:
    """One account, acting at one assurance.

    `mfa_device_id` names the second factor a code was verified against. It is
    set if and only if the assurance is MFA_VERIFIED: ValueError is raised
    otherwise.
    """

    user: User
    assurance: Assurance
    mfa_device_id: int | None = None

    def __post_init__(self) -> None:
        if (self.assurance is Assurance.MFA_VERIFIED) != (self.mfa_device_id is not None):
            raise ValueError("A device is named if and only if the assurance is MFA_VERIFIED.")
