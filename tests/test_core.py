import math
import unittest

from flight_duty_period_utils import (
    FlightDutyPeriod,
    RestCalculator,
    DutyPeriodError,
)


class TestFlightDutyPeriodConstruction(unittest.TestCase):
    def test_single_sector(self):
        fdp = FlightDutyPeriod(
            report_time=1000,
            report_acclimatised=True,
            sectors=[(1100, 1200)],
        )
        self.assertEqual(fdp.num_sectors, 1)
        self.assertEqual(fdp.flight_time, 100)
        self.assertEqual(fdp.last_block_on, 1200)

    def test_multiple_sectors_ordered(self):
        fdp = FlightDutyPeriod(
            report_time=1000,
            report_acclimatised=True,
            sectors=[(1100, 1200), (1300, 1400), (1500, 1600)],
        )
        self.assertEqual(fdp.num_sectors, 3)
        self.assertEqual(fdp.flight_time, 300)
        self.assertEqual(fdp.last_block_on, 1600)

    def test_empty_sectors_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, True, [])

    def test_non_int_report_time_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000.0, True, [(1100, 1200)])

    def test_negative_report_time_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(-1, True, [(1100, 1200)])

    def test_non_bool_acclimatised_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, 1, [(1100, 1200)])

    def test_sector_off_after_on_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, True, [(1200, 1100)])

    def test_sector_off_equals_on_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, True, [(1100, 1100)])

    def test_sector_off_before_report_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1100, True, [(1000, 1200)])

    def test_sectors_not_monotonic_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, True, [(1100, 1400), (1200, 1300)])

    def test_sector_wrong_shape_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, True, [(1100, 1200, 1300)])

    def test_sector_non_int_times_rejected(self):
        with self.assertRaises(DutyPeriodError):
            FlightDutyPeriod(1000, True, [(1100.0, 1200)])


class TestMaxFDP(unittest.TestCase):
    def test_acclimatised_single_sector(self):
        fdp = FlightDutyPeriod(0, True, [(0, 1)])
        self.assertEqual(fdp.max_fdp_seconds(), 13 * 3600)

    def test_acclimatised_three_sectors(self):
        fdp = FlightDutyPeriod(0, True, [(0, 1), (2, 3), (4, 5)])
        self.assertEqual(fdp.max_fdp_seconds(), 12 * 3600)

    def test_acclimatised_five_sectors(self):
        fdp = FlightDutyPeriod(0, True, [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)])
        self.assertEqual(fdp.max_fdp_seconds(), 11 * 3600)

    def test_acclimatised_eight_sectors(self):
        fdp = FlightDutyPeriod(
            0, True, [(i, i + 1) for i in range(0, 16, 2)]
        )
        self.assertEqual(fdp.max_fdp_seconds(), 9 * 3600)

    def test_unacclimatised_flat_cap(self):
        fdp = FlightDutyPeriod(0, False, [(0, 1)])
        self.assertEqual(fdp.max_fdp_seconds(), 13 * 3600)
        fdp2 = FlightDutyPeriod(0, False, [(0, 1)] * 8 if False else [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9), (10, 11), (12, 13), (14, 15)])
        self.assertEqual(fdp2.max_fdp_seconds(), 13 * 3600)

    def test_augmented_extends_limit(self):
        fdp = FlightDutyPeriod(0, True, [(0, 1)])
        self.assertEqual(fdp.max_fdp_seconds(augmented=True), 15 * 3600)
        fdp2 = FlightDutyPeriod(0, True, [(0, 1), (2, 3), (4, 5)])
        self.assertEqual(fdp2.max_fdp_seconds(augmented=True), 14 * 3600)
        fdp3 = FlightDutyPeriod(0, True, [(0, 1), (2, 3), (4, 5), (6, 7), (8, 9)])
        self.assertEqual(fdp3.max_fdp_seconds(augmented=True), 12 * 3600)

    def test_within_fdp_limit_true(self):
        # 1 sector, acclimatised, limit 13h. Duty span 1h + 30min post = 5400s.
        fdp = FlightDutyPeriod(0, True, [(0, 3600)])
        self.assertTrue(fdp.is_within_fdp_limit())

    def test_within_fdp_limit_false(self):
        # span exceeds 13h limit
        fdp = FlightDutyPeriod(0, True, [(0, 13 * 3600)])
        # duty end = 13h + 30min; limit 13h
        self.assertFalse(fdp.is_within_fdp_limit())


class TestRestCalculator(unittest.TestCase):
    def test_duty_end(self):
        calc = RestCalculator(post_flight_duty_minutes=30)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        self.assertEqual(calc.duty_end(fdp), 100 + 1800)

    def test_duty_end_custom_post_flight(self):
        calc = RestCalculator(post_flight_duty_minutes=45)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        self.assertEqual(calc.duty_end(fdp), 100 + 2700)

    def test_rest_between(self):
        calc = RestCalculator(post_flight_duty_minutes=30)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        # end = 100 + 1800 = 1900; next report 10000 -> rest = 8100
        self.assertEqual(calc.rest_between(fdp, 10000), 8100)

    def test_rest_between_negative_on_overlap(self):
        calc = RestCalculator(post_flight_duty_minutes=30)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        # next report before duty end -> negative rest
        self.assertEqual(calc.rest_between(fdp, 500), -1400)

    def test_minimum_rest_without_local_day(self):
        calc = RestCalculator()
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        self.assertEqual(calc.minimum_rest_seconds(fdp), 12 * 3600)

    def test_minimum_rest_with_local_night_available(self):
        # release at 1900; local day start 2000 -> local night [2000, 22400)
        calc = RestCalculator(local_day_start=2000)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        self.assertEqual(calc.minimum_rest_seconds(fdp), 10 * 3600)

    def test_minimum_rest_with_local_night_not_available(self):
        # release at 2100; local day start 2000 -> release after local night start
        calc = RestCalculator(local_day_start=2000)
        fdp = FlightDutyPeriod(0, True, [(0, 300)])  # block_on 300 + 1800 = 2100
        self.assertEqual(calc.minimum_rest_seconds(fdp), 12 * 3600)

    def test_is_rest_sufficient_true(self):
        calc = RestCalculator(post_flight_duty_minutes=30)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        # end 1900; min 12h = 43200; sufficient if next report >= 45100
        self.assertTrue(calc.is_rest_sufficient(fdp, 45100))
        self.assertFalse(calc.is_rest_sufficient(fdp, 45000))

    def test_is_rest_sufficient_with_local_night(self):
        calc = RestCalculator(post_flight_duty_minutes=30, local_day_start=2000)
        fdp = FlightDutyPeriod(0, True, [(0, 100)])
        # end 1900 <= 2000 -> min 10h = 36000; sufficient if >= 37900
        self.assertTrue(calc.is_rest_sufficient(fdp, 37900))
        self.assertFalse(calc.is_rest_sufficient(fdp, 37800))

    def test_invalid_post_flight_duty_minutes(self):
        with self.assertRaises(ValueError):
            RestCalculator(post_flight_duty_minutes=-1)
        with self.assertRaises(ValueError):
            RestCalculator(post_flight_duty_minutes=1.0)

    def test_invalid_local_day_start(self):
        with self.assertRaises(ValueError):
            RestCalculator(local_day_start=-1)
        with self.assertRaises(ValueError):
            RestCalculator(local_day_start=1.0)

    def test_duty_end_type_error(self):
        calc = RestCalculator()
        with self.assertRaises(TypeError):
            calc.duty_end("not an fdp")

    def test_rest_between_type_errors(self):
        calc = RestCalculator()
        fdp = FlightDutyPeriod(0, True, [(0, 1)])
        with self.assertRaises(TypeError):
            calc.rest_between("not fdp", 100)
        with self.assertRaises(ValueError):
            calc.rest_between(fdp, -1)
        with self.assertRaises(ValueError):
            calc.rest_between(fdp, 1.0)

    def test_minimum_rest_seconds_type_error(self):
        calc = RestCalculator()
        with self.assertRaises(TypeError):
            calc.minimum_rest_seconds("not fdp")

    def test_release_time_not_implemented(self):
        # release_time on the FDP itself is intentionally not implemented
        # because it needs post_flight_duty_minutes from the calculator.
        fdp = FlightDutyPeriod(0, True, [(0, 1)])
        with self.assertRaises(NotImplementedError):
            _ = fdp.release_time


if __name__ == "__main__":
    unittest.main()
