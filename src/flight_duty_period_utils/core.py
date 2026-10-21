"""
Flight Duty Period (FDP) and rest calculation utilities.

This module implements a simplified model of crew FDP and minimum-rest
rules inspired by the structure of EASA FTL and FAA Part 117. The
model is deliberately small and self-contained; it is not a certified
implementation of any specific regulation. The intent is to give
scheduling tools and tests a deterministic, auditable building block.

Design decisions
---------------
1. All times are UTC instants represented as seconds-since-epoch
   integers. This sidesteps timezone ambiguity entirely. Airlines
   operate across timezones; storing a local wall-clock time is a
   known source of off-by-one rest miscalculations.
2. Rest is measured from "wheels-down + 30 min post-flight duty" to
   the next report time, per the common FTL definition of rest as
   a continuous period during which a crew member is free of all
   duty. The 30-minute buffer is configurable on the calculator.
3. Duty span counts the entire period from report to release,
   including post-flight duty. We do not split out positioning
   (deadheading) vs. flight time because a correct general
   treatment of that requires per-carrier policy; we refuse to
   guess.
"""

from __future__ import annotations


class DutyPeriodError(ValueError):
    """Raised when an FDP is structurally invalid.

    We use a ValueError subclass rather than bare ValueError so that
    callers can distinguish FDP-domain errors from generic value errors
    originating elsewhere in their stack.
    """


class FlightDutyPeriod:
    """A single flight duty period.

    Parameters
    ----------
    report_time : int
        UTC epoch seconds at which the crew member reports for duty.
    report_acclimatised : bool
        Whether the crew member is acclimatised to the local time zone
        at report. This affects the maximum FDP in some regulations;
        here it is used to pick between two limits.
    sectors : list[tuple[int, int]]
        Ordered list of (block_off, block_on) epoch-second pairs.
        Each pair is a single flight sector. Block-off is engine
        start for take-off; block-on is engine stop after landing.

    Notes
    -----
    Validation is eager: the constructor raises on any inconsistency
    so that downstream code can assume invariants hold.
    """

    def __init__(self, report_time, report_acclimatised, sectors):
        if not isinstance(report_time, int):
            raise DutyPeriodError("report_time must be int epoch seconds")
        if report_time < 0:
            raise DutyPeriodError("report_time must be non-negative")
        if not isinstance(report_acclimatised, bool):
            raise DutyPeriodError("report_acclimatised must be bool")
        if not isinstance(sectors, list):
            raise DutyPeriodError("sectors must be a list")
        if not sectors:
            raise DutyPeriodError("sectors must not be empty")

        normalised = []
        for idx, pair in enumerate(sectors):
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise DutyPeriodError(
                    "sector %d must be a 2-tuple of epoch seconds" % idx
                )
            off, on = pair
            if not isinstance(off, int) or not isinstance(on, int):
                raise DutyPeriodError(
                    "sector %d times must be int epoch seconds" % idx
                )
            if off < 0 or on < 0:
                raise DutyPeriodError(
                    "sector %d times must be non-negative" % idx
                )
            if off >= on:
                raise DutyPeriodError(
                    "sector %d block_off must be before block_on" % idx
                )
            if off < report_time:
                raise DutyPeriodError(
                    "sector %d block_off is before report_time" % idx
                )
            if idx > 0 and off < normalised[-1][1]:
                raise DutyPeriodError(
                    "sector %d block_off is before previous block_on" % idx
                )
            normalised.append((off, on))

        self._report_time = report_time
        self._acclimatised = report_acclimatised
        self._sectors = tuple(normalised)

    @property
    def report_time(self):
        """UTC epoch seconds at which the crew member reported."""
        return self._report_time

    @property
    def report_acclimatised(self):
        """True if the crew was acclimatised at report time."""
        return self._acclimatised

    @property
    def sectors(self):
        """Tuple of (block_off, block_on) pairs, in order."""
        return self._sectors

    @property
    def last_block_on(self):
        """Block-on of the final sector; the reference for post-flight duty."""
        return self._sectors[-1][1]

    @property
    def release_time(self):
        """Time the crew is released from duty.

        We define release as last_block_on + post_flight_duty_minutes,
        where post_flight_duty_minutes is supplied to the RestCalculator
        at computation time. This period represents post-flight
        shutdown paperwork and passenger handover that must occur
        before rest can begin.
        """
        raise NotImplementedError(
            "release_time requires post_flight_duty_minutes; "
            "use RestCalculator.duty_end()"
        )

    @property
    def flight_time(self):
        """Sum of (block_on - block_off) across all sectors, in seconds."""
        return sum(on - off for off, on in self._sectors)

    @property
    def num_sectors(self):
        """Number of sectors flown in this FDP."""
        return len(self._sectors)

    def max_fdp_seconds(self, augmented=False):
        """Maximum permitted FDP duration for this duty.

        Parameters
        ----------
        augmented : bool
            If True the crew is augmented (a relief pilot is carried),
            which extends the limit.

        Notes
        -----
        The limit depends on report acclimatisation, sector count,
        and augmentation. We use a compact lookup table rather than
        a chain of if/else because the full regulation is a matrix
        over those three dimensions; a table keeps the structure
        visible.
        """
        n = self.num_sectors
        if augmented:
            # Augmented limits under EARA O7.1 table
            if n == 1:
                return 15 * 3600
            elif 2 <= n <= 3:
                return 14 * 3600
            elif 4 <= n <= 6:
                return 12 * 3600
            else:
                return 11 * 3600
        # Non-augmented
        if not self._acclimatised:
            # In-unacclimatised (home-base) crew get a flat cap
            return 13 * 3600
        if n == 1:
            return 13 * 3600
        elif 2 <= n <= 3:
            return 12 * 3600
        elif 4 <= n <= 6:
            return 11 * 3600
        else:
            return 9 * 3600

    def is_within_fdp_limit(self, augmented=False, post_flight_duty_minutes=30):
        """Check that the duty span does not exceed the FDP limit.

        Parameters
        ----------
        augmented : bool
            Whether the crew is augmented.
        post_flight_duty_minutes : int
            Minutes of duty after last block_on before release.

        Returns
        -------
        bool
            True if duty span <= max FDP.
        """
        end = self.last_block_on + post_flight_duty_minutes * 60
        span = end - self._report_time
        return span <= self.max_fdp_seconds(augmented=augmented)


class RestCalculator:
    """Computes minimum rest and validates rest between two duties.

    Parameters
    ----------
    post_flight_duty_minutes : int
        Minutes of duty after last block_on before the crew is
        released. This is the time for shutdown, paperwork, and
        passenger handover. We treat it as a fixed buffer because a
        general model would need per-airport and per-carrier policy.
    local_day_start : int, optional
        UTC epoch seconds representing 00:00 local on the day after
        the previous FDP's release. If provided, it is used to
        determine whether a local-night rest is achieved; otherwise
        we fall back to a longer flat minimum.

    Notes
    -----
    Rest is defined as the gap between release of one duty and report
    of the next. We expose :meth:`rest_between` to compute that gap
    and :meth:`minimum_rest_seconds` to get the required minimum.
    """

    def __init__(self, post_flight_duty_minutes=30, local_day_start=None):
        if not isinstance(post_flight_duty_minutes, int):
            raise ValueError("post_flight_duty_minutes must be int")
        if post_flight_duty_minutes < 0:
            raise ValueError("post_flight_duty_minutes must be non-negative")
        if local_day_start is not None:
            if not isinstance(local_day_start, int) or local_day_start < 0:
                raise ValueError("local_day_start must be non-negative int or None")
        self._post_flight_duty_minutes = post_flight_duty_minutes
        self._local_day_start = local_day_start

    @property
    def post_flight_duty_minutes(self):
        return self._post_flight_duty_minutes

    @property
    def local_day_start(self):
        return self._local_day_start

    def duty_end(self, fdp):
        """Return the UTC epoch second at which the given FDP ends.

        This is last_block_on + post_flight_duty_minutes.
        """
        if not isinstance(fdp, FlightDutyPeriod):
            raise TypeError("fdp must be a FlightDutyPeriod")
        return fdp.last_block_on + self._post_flight_duty_minutes * 60

    def rest_between(self, prev_fdp, next_report_time):
        """Seconds of rest between the end of one FDP and the next report.

        Parameters
        ----------
        prev_fdp : FlightDutyPeriod
            The preceding duty.
        next_report_time : int
            UTC epoch seconds at which the crew next reports.

        Returns
        -------
        int
            Rest in seconds. Negative if duties overlap (which is an
            error condition callers should detect).
        """
        if not isinstance(prev_fdp, FlightDutyPeriod):
            raise TypeError("prev_fdp must be a FlightDutyPeriod")
        if not isinstance(next_report_time, int) or next_report_time < 0:
            raise ValueError("next_report_time must be non-negative int")
        end = self.duty_end(prev_fdp)
        return next_report_time - end

    def minimum_rest_seconds(self, prev_fdp):
        """Minimum rest required after the given FDP.

        The rule modelled here: at least 10 hours, or 12 hours if a
        local-night opportunity (sleep during local 00:00–06:00) is
        not guaranteed.

        If ``local_day_start`` is None we cannot verify a local night,
        so we return the conservative 12-hour minimum.
        """
        if not isinstance(prev_fdp, FlightDutyPeriod):
            raise TypeError("prev_fdp must be a FlightDutyPeriod")
        if self._local_day_start is None:
            return 12 * 3600
        end = self.duty_end(prev_fdp)
        # Local night spans [local_day_start, local_day_start + 6h).
        # To have a local-night opportunity, release must be at or
        # before local_day_start so the crew is free to sleep through
        # the whole local night.
        if end <= self._local_day_start:
            return 10 * 3600
        return 12 * 3600

    def is_rest_sufficient(self, prev_fdp, next_report_time):
        """Return True if rest between duties meets the minimum."""
        rest = self.rest_between(prev_fdp, next_report_time)
        return rest >= self.minimum_rest_seconds(prev_fdp)
