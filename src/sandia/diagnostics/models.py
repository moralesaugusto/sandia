"""Shared result shapes for the diagnostic system.

Every diagnostic check (server/subnet/pool/client/...) produces one or more
Findings and rolls them up into a DiagnosticResult. This is the only shape
the UI needs to know how to render, regardless of which object was
diagnosed - see routers/diagnostics.py and templates/diagnostics/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class Confidence(str, Enum):
    CONFIRMED = "confirmed"  # directly computed/observed from the data - not an inference
    STRONG = "strong"  # multiple consistent signals, but not directly proven
    POSSIBLE = "possible"  # one weak or indirect signal
    UNKNOWN = "unknown"  # not enough evidence to say anything


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

    @property
    def status(self) -> Status:
        if not self.findings:
            return Status.UNKNOWN
        return max((f.status for f in self.findings), key=lambda s: _STATUS_RANK[s])


def worst_status(statuses: list[Status]) -> Status:
    if not statuses:
        return Status.UNKNOWN
    return max(statuses, key=lambda s: _STATUS_RANK[s])
