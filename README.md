# flight_duty_period_utils

A small, dependency-free library for calculating flight crew duty periods and rest requirements, inspired by the structure of EASA FTL and FAA Part 117.

## Usage

```python
from flight_duty_period_utils import FlightDutyPeriod, RestCalculator

fdp = FlightDutyPeriod(
    report_time=1_700_000_000,
    report_acclimatised=True,
    sectors=[
        (1_700_003_600, 1_700_006_600),  # 1h flight
    ],
)
print(fdp.flight_time)           # 3600
print(fdp.max_fdp_seconds())      # 46800 (13h, single sector, acclimatised)
print(fdp.is_within_fdp_limit()) # True

calc = RestCalculator(post_flight_duty_minutes=30)
end = calc.duty_end(fdp)                      # last block_on + 1800s
rest = calc.rest_between(fdp, 1_700_050_000)  # seconds until next report
ok = calc.is_rest_sufficient(fdp, 1_700_050_000)
```

All times are UTC epoch seconds (integers). The library uses no timezone conversion; storing a local wall-clock time is a known source of off-by-one rest miscalculations, so we refuse to do it.

## Why this exists

Crew scheduling systems need a deterministic, auditable way to check whether a proposed duty sequence stays within FDP limits and leaves enough rest before the next report. The full regulations are long and carrier-specific; this library captures the common skeleton: a sector-list model, an FDP cap that varies with acclimatisation/sector-count/augmentation, and a rest minimum that accounts for the local-night rule. The trade-off is that it is not a certified implementation of any one regulation; it is a building block for tools that can layer their own carrier policy on top.

## Edge cases

- `FlightDutyPeriod.release_time` is intentionally not implemented on the period itself. Release time depends on `post_flight_duty_minutes`, which lives on `RestCalculator`. Call `RestCalculator.duty_end(fdp)` instead.
- Sectors must be strictly time-ordered and each `block_off` must be at or after `report_time`; the constructor raises `DutyPeriodError` otherwise.
- `rest_between` returns a negative int when duties overlap; callers should check for this.
- If `local_day_start` is `None`, the minimum rest defaults to a conservative 12 hours, because we cannot verify a local-night opportunity.

## Limits

This library does not model split duty, in-flight rest, positioning (deadheading) as a separate concept from flight time, or Commander's Discretion. If you need those, layer them on top; do not expect this library to guess.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

## Limitations

Values are coerced to floats, so very large integers lose precision. If you need
exact integer aggregates over a window, this is the wrong tool.

## Contributing

Issues and pull requests are welcome. Please keep the dependency list empty —
that constraint is the point of the project, not an oversight.

