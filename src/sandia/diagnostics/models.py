"""Shared result shapes for the diagnostic system.

Every diagnostic check (server/subnet/pool/client/...) produces one or more
Findings and rolls them up into a DiagnosticResult. This is the only shape
the UI needs to know how to render, regardless of which object was
diagnosed - see routers/diagnostics.py and templates/diagnostics/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..i18n import N_, _


class Status(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        return _(_STATUS_LABELS[self])


class Confidence(str, Enum):
    CONFIRMED = "confirmed"  # directly computed/observed from the data - not an inference
    STRONG = "strong"  # multiple consistent signals, but not directly proven
    POSSIBLE = "possible"  # one weak or indirect signal
    UNKNOWN = "unknown"  # not enough evidence to say anything

    @property
    def label(self) -> str:
        return _(_CONFIDENCE_LABELS[self])


_STATUS_LABELS = {Status.HEALTHY: N_("healthy"), Status.WARNING: N_("warning"), Status.CRITICAL: N_("critical"), Status.UNKNOWN: N_("unknown")}
_CONFIDENCE_LABELS = {
    Confidence.CONFIRMED: N_("confirmed"),
    Confidence.STRONG: N_("strong"),
    Confidence.POSSIBLE: N_("possible"),
    Confidence.UNKNOWN: N_("unknown"),
}


_STATUS_RANK = {Status.HEALTHY: 0, Status.UNKNOWN: 1, Status.WARNING: 2, Status.CRITICAL: 3}


@dataclass
class Evidence:
    label: str
    value: str


@dataclass
class Action:
    label: str
    url: str


@dataclass
class Finding:
    status: Status
    problem: str
    root_cause: str
    confidence: Confidence
    evidence: list[Evidence] = field(default_factory=list)
    impact: str = ""
    actions: list[Action] = field(default_factory=list)


@dataclass
class FlowStep:
    """One stage of the client DHCP flow (Client -> DHCP activity -> Subnet
    -> Reservation -> Pool -> Address availability -> DHCP response ->
    Lease). `status` reflects whether this stage looks fine, is the
    problem, or simply has no evidence either way."""

    name: str
    status: Status
    detail: str
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class DiagnosticResult:
    title: str
    target_description: str
    findings: list[Finding] = field(default_factory=list)
    steps: list[FlowStep] = field(default_factory=list)
    # Set by diagnose_client() when a MAC was resolved (directly, or via a
    # reservation/lease lookup) - lets the UI offer "Open device" without
    # re-deriving identity the caller already has.
    resolved_mac: str | None = None

    @property
    def status(self) -> Status:
        if not self.findings:
            return Status.UNKNOWN
        return max((f.status for f in self.findings), key=lambda s: _STATUS_RANK[s])


def worst_status(statuses: list[Status]) -> Status:
    if not statuses:
        return Status.UNKNOWN
    return max(statuses, key=lambda s: _STATUS_RANK[s])
