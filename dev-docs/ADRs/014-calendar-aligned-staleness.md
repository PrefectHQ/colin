# ADR 014: Calendar-Aligned Staleness

## Status

Accepted

## Context

Colin documents can specify time-based staleness thresholds (`stale: 1d`). Users need two distinct behaviors:

1. **Elapsed time**: "rebuild 24 hours after last compile"
2. **Calendar boundaries**: "rebuild when the calendar day changes"

These are different. A document compiled at 11pm with `stale: 1d` won't rebuild until 11pm tomorrow. But with calendar alignment, it should rebuild at midnight.

## Decision

Use the `c` prefix to indicate calendar-aligned staleness:

- `1d` = 1 day elapsed since compile
- `1cd` = new calendar day (midnight boundary)
- `30m` = 30 minutes elapsed
- `30cm` = at :00 and :30 boundaries

### Validation Constraints

Calendar-aligned values must divide evenly into their containing period to create predictable boundaries:

| Unit | Valid values | Reason |
|------|-------------|--------|
| `cm` | 1,2,3,4,5,6,10,12,15,20,30,60 | Must divide 60 minutes |
| `ch` | 1,2,3,4,6,8,12,24 | Must divide 24 hours |
| `cd` | 1 only | Days don't subdivide into weeks predictably |
| `cw` | 1 only | Weeks don't subdivide into months predictably |
| `cM` | 1,2,3,4,6,12 | Must divide 12 months |
| `cQ` | 1,2,4 | Must divide 4 quarters |

Values like `3cd` or `7cm` are rejected because they would create boundaries that don't align with natural calendar periods.

### Implementation

Minutes and hours use epoch-based periods (fixed boundaries that don't shift). Days and larger use natural calendar boundaries (midnight, Monday, 1st of month, quarter starts).

## Alternatives Considered

**Named schedules** (`stale: quarterly`): More readable but less flexible. Doesn't allow `2cM` (bimonthly) or `15cm` (quarter-hourly).

**Cron syntax**: Powerful but complex for the common cases. Overkill when users just want "refresh monthly."

**Epoch-based for all units**: Consistent but creates unintuitive boundaries for days and larger (why would "every 3 days" start from 1970?).
