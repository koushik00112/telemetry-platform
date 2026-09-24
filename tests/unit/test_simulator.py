from datetime import UTC, datetime, timedelta

import pytest

from simulator.model import METRICS, DeviceModel, Fault

T0 = datetime(2026, 9, 28, tzinfo=UTC)


def run(model, steps=500):
    out = []
    for i in range(steps):
        out.extend(model.step(T0 + timedelta(minutes=i)))
    model.close(T0 + timedelta(minutes=steps))
    return out


def test_same_seed_reproduces_exactly():
    a = run(DeviceModel("d", 0, seed=7, fault_rate=0.05))
    b = run(DeviceModel("d", 0, seed=7, fault_rate=0.05))
    assert a == b


def test_different_seed_or_device_index_differs():
    base = run(DeviceModel("d", 0, seed=7, fault_rate=0.05))
    assert run(DeviceModel("d", 0, seed=8, fault_rate=0.05)) != base
    assert run(DeviceModel("d", 1, seed=7, fault_rate=0.05)) != base


def test_zero_fault_rate_emits_every_metric_every_step_unlabelled():
    model = DeviceModel("d", 0, seed=1, fault_rate=0.0)
    samples = run(model, steps=100)
    assert len(samples) == 100 * len(METRICS)
    assert all(s.fault is None for s in samples)
    assert model.events == []


def test_faults_are_labelled_and_recorded_as_events():
    model = DeviceModel("d", 0, seed=3, fault_rate=0.2)
    samples = run(model, steps=2000)
    kinds = {e.fault for e in model.events}
    assert kinds == set(Fault)  # every fault type shows up over 2000 steps at this rate
    assert {s.fault for s in samples if s.fault} == kinds - {Fault.dropout}
    assert all(e.start <= e.end for e in model.events)


def test_dropout_emits_nothing_and_other_steps_emit_every_metric():
    model = DeviceModel("d", 0, seed=3, fault_rate=0.2)
    counts = [len(model.step(T0 + timedelta(minutes=i))) for i in range(2000)]
    assert 0 in counts
    assert set(counts) == {0, len(METRICS)}


def test_values_stay_within_physical_bounds():
    samples = run(DeviceModel("d", 0, seed=5, fault_rate=0.3), steps=3000)
    by_metric = {m.name: [s.value for s in samples if s.metric == m.name] for m in METRICS}
    assert min(by_metric["humidity_pct"]) >= 0
    assert max(by_metric["humidity_pct"]) <= 100
    assert min(by_metric["vibration_rms"]) >= 0


def test_stuck_fault_repeats_one_value():
    model = DeviceModel("d", 0, seed=11, fault_rate=0.2)
    samples = run(model, steps=3000)
    stuck = [s for s in samples if s.fault is Fault.stuck]
    assert stuck
    # Within one stuck episode (same metric, consecutive), the value never changes.
    episodes: dict[tuple, set] = {}
    for e in (e for e in model.events if e.fault is Fault.stuck):
        vals = {s.value for s in stuck if s.metric == e.metric and e.start <= s.ts < e.end}
        episodes[(e.metric, e.start)] = vals
    assert all(len(v) == 1 for v in episodes.values() if v)


def test_rejects_invalid_fault_rate():
    with pytest.raises(ValueError, match="fault_rate"):
        DeviceModel("d", 0, seed=1, fault_rate=1.5)
