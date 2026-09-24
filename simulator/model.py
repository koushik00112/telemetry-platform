"""Synthetic device model with seeded fault injection.

Everything this module produces is synthetic. The fault sequence depends only on
(seed, device index, step number), so a run can be reproduced exactly.
"""

import math
import random
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Fault(StrEnum):
    spike = "spike"  # one sample far off the normal range
    stuck = "stuck"  # sensor repeats its last value
    drift = "drift"  # slow ramp away from the true value
    dropout = "dropout"  # device sends nothing


@dataclass(frozen=True)
class MetricSpec:
    name: str
    baseline: float
    noise: float
    # Size of a fault on this metric, in the metric's own units.
    fault_scale: float
    lo: float = -math.inf
    hi: float = math.inf


METRICS = (
    MetricSpec("temperature_c", baseline=22.0, noise=0.2, fault_scale=15.0),
    MetricSpec("humidity_pct", baseline=45.0, noise=1.0, fault_scale=35.0, lo=0.0, hi=100.0),
    MetricSpec("vibration_rms", baseline=0.5, noise=0.05, fault_scale=2.0, lo=0.0),
)

DURATION_STEPS = {
    Fault.spike: (1, 1),
    Fault.stuck: (10, 60),
    Fault.drift: (30, 120),
    Fault.dropout: (5, 30),
}


@dataclass(frozen=True)
class Sample:
    metric: str
    value: float
    ts: datetime
    fault: Fault | None


@dataclass
class ActiveFault:
    kind: Fault
    metric: str | None  # None for dropout, which silences every metric
    start_step: int
    length: int
    sign: float
    stuck_value: float | None = None


@dataclass(frozen=True)
class FaultEvent:
    device: str
    fault: Fault
    metric: str | None
    start: datetime
    end: datetime


class DeviceModel:
    def __init__(self, name: str, index: int, seed: int, fault_rate: float) -> None:
        if not 0 <= fault_rate <= 1:
            raise ValueError("fault_rate must be between 0 and 1")
        self.name = name
        self.fault_rate = fault_rate
        # Independent stream per device, so adding devices doesn't change existing ones.
        self.rng = random.Random(seed * 1_000_003 + index)  # noqa: S311 - simulation, not crypto
        self.step_no = 0
        self.active: ActiveFault | None = None
        self.active_start_ts: datetime | None = None
        self.last_value: dict[str, float] = {}
        self.events: list[FaultEvent] = []

    def step(self, ts: datetime) -> list[Sample]:
        """Advance one tick and return the samples the device emits at ts."""
        self._maybe_end_fault(ts)
        self._maybe_start_fault(ts)
        self.step_no += 1

        fault = self.active
        if fault is not None and fault.kind is Fault.dropout:
            return []

        samples = []
        for spec in METRICS:
            value = self._normal_value(spec, ts)
            label = None
            if fault is not None and fault.metric == spec.name:
                value = self._apply_fault(fault, spec, value)
                label = fault.kind
            value = min(max(value, spec.lo), spec.hi)
            self.last_value[spec.name] = value
            samples.append(Sample(spec.name, round(value, 4), ts, label))
        return samples

    def _normal_value(self, spec: MetricSpec, ts: datetime) -> float:
        value = spec.baseline + self.rng.gauss(0, spec.noise)
        if spec.name == "temperature_c":
            hour = ts.hour + ts.minute / 60
            value += 3 * math.sin(2 * math.pi * (hour - 9) / 24)  # daily cycle, peak mid-afternoon
        return value

    def _apply_fault(self, fault: ActiveFault, spec: MetricSpec, value: float) -> float:
        progress = (self.step_no - fault.start_step) / fault.length
        if fault.kind is Fault.spike:
            return value + fault.sign * spec.fault_scale * self.rng.uniform(0.8, 1.5)
        if fault.kind is Fault.stuck:
            if fault.stuck_value is None:
                fault.stuck_value = self.last_value.get(spec.name, spec.baseline)
            return fault.stuck_value
        if fault.kind is Fault.drift:
            return value + fault.sign * spec.fault_scale * progress
        return value

    def _maybe_start_fault(self, ts: datetime) -> None:
        if self.active is not None or self.rng.random() >= self.fault_rate:
            return
        kind = self.rng.choice(list(Fault))
        lo, hi = DURATION_STEPS[kind]
        metric = None if kind is Fault.dropout else self.rng.choice(METRICS).name
        self.active = ActiveFault(
            kind=kind,
            metric=metric,
            start_step=self.step_no,
            length=self.rng.randint(lo, hi),
            sign=self.rng.choice((-1.0, 1.0)) if metric != "vibration_rms" else 1.0,
        )
        self.active_start_ts = ts

    def _maybe_end_fault(self, ts: datetime) -> None:
        fault = self.active
        if fault is None or self.step_no - fault.start_step < fault.length:
            return
        assert self.active_start_ts is not None
        self.events.append(
            FaultEvent(self.name, fault.kind, fault.metric, self.active_start_ts, ts)
        )
        self.active = None
        self.active_start_ts = None

    def close(self, ts: datetime) -> None:
        """Record a fault still running when the simulation stops."""
        if self.active is not None and self.active_start_ts is not None:
            self.events.append(
                FaultEvent(
                    self.name, self.active.kind, self.active.metric, self.active_start_ts, ts
                )
            )
            self.active = None
