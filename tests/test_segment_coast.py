"""Regressões nas decisões geométricas e metodológicas da etapa 2."""

import sys
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))

from segment_coast import CoastIndex, CoastPath, adaptive, classify, geometry_at_dateline


class CoastGeometryTest(unittest.TestCase):
    def test_nearest_is_on_edge_instead_of_vertex(self):
        path = CoastPath("TEST", [(0, 0), (1, 0)])
        selected, along, (lon, lat), distance = CoastIndex([path]).nearest(0.323, 0.1)
        self.assertEqual(selected.id, "TEST")
        self.assertAlmostEqual(lon, 0.323, places=9)
        self.assertAlmostEqual(lat, 0, places=9)
        self.assertAlmostEqual(along, 35.916, places=2)
        self.assertAlmostEqual(distance, 11.1195, places=4)
        segments = path.cut(25)
        self.assertAlmostEqual(sum(row["length_km"] for row in segments), path.length, places=3)
        self.assertTrue(all(a["coordinates"][-1] == b["coordinates"][0] for a, b in zip(segments, segments[1:])))

    def test_antimeridian_is_short_and_geojson_has_no_world_spanning_edges(self):
        path = CoastPath("SEAM", [(179.9, 0), (-179.9, 0)])
        self.assertAlmostEqual(path.length, 22.239, places=3)
        _, _, (_, lat), distance = CoastIndex([path]).nearest(180, 0.03)
        self.assertAlmostEqual(lat, 0, places=9)
        self.assertAlmostEqual(distance, 3.33585, places=4)
        geometry = geometry_at_dateline(path.cut(25)[0]["coordinates"])
        self.assertEqual(geometry["type"], "MultiLineString")
        for part in geometry["coordinates"]:
            self.assertTrue(all(abs(a[0] - b[0]) <= 180 for a, b in zip(part, part[1:])))


class AdaptiveRegionsTest(unittest.TestCase):
    def test_same_day_is_not_counted_twice_and_existing_region_is_protected(self):
        segments = [{"id": str(i)} for i in range(7)]
        days = defaultdict(set, {"0": set(range(10)), "1": set(range(6)), "2": set(range(6)), "5": set(range(8, 13))})
        counts = Counter({"0": 15, "1": 8, "2": 6, "5": 5})
        regions = adaptive(segments, days, counts)
        self.assertIn((0,), regions)
        self.assertIn((2, 3, 4, 5), regions)
        self.assertEqual(len(days["1"] | days["2"]), 6)
        self.assertTrue(all(0 not in span for span in regions if len(span) > 1))

    def test_closed_island_can_merge_through_its_index_seam(self):
        segments = [{"id": str(i)} for i in range(6)]
        days = defaultdict(set, {"0": set(range(6)), "5": set(range(6, 11))})
        counts = Counter({"0": 6, "5": 5})
        self.assertEqual(adaptive(segments, days, counts, closed=True), [(5, 0)])
        self.assertEqual(adaptive(segments, days, counts, closed=False), [(0,), (5,)])


class AssignmentPolicyTest(unittest.TestCase):
    class Country:
        def check(self, label, longitude, latitude, snapped):
            if label in ("USA", "PUERTO RICO"):
                return "assigned", "country_near_snap"
            return "country_mismatch", "point_and_snap_outside_expected_country"

    class State:
        def check(self, country, state, snapped):
            return state != "OTHER STATE"

    def setUp(self):
        self.index = CoastIndex([CoastPath("TEST", [(0, 0), (5, 0)])])

    def event(self, place, longitude=1, latitude=0.4, state="CALIFORNIA", country="USA"):
        return dict(country=country, state=state, location=place, lon=longitude, lat=latitude)

    def assignments(self, events, reviewed=None):
        return classify(events, self.index, self.Country(), 25, 75, self.State(), reviewed or {})

    def test_extension_needs_coastal_place_and_geographic_context(self):
        cases = [
            self.event("Example Beach"), self.event("Other Beach", longitude=2, state="OTHER STATE"),
            self.event("Disney Typhoon Lagoon Water Park", longitude=3),
            self.event("Open Sea", longitude=4), self.event("Example Beach", longitude=4.5, country="OTHER"),
        ]
        extended, bad_state, artificial, generic, bad_country = self.assignments(cases)
        self.assertEqual(extended.method, "extended_geocode")
        self.assertEqual(bad_state.detail, "extended_state_mismatch")
        self.assertEqual(artificial.detail, "extended_explicit_noncoastal_context")
        self.assertIsNone(generic.method)
        self.assertEqual(bad_country.status, "country_mismatch")

    def test_shared_geocode_with_different_names_is_not_extended(self):
        matches = self.assignments([self.event("First Beach"), self.event("Second Beach")])
        self.assertTrue(all(row.detail == "extended_shared_geocode" and not row.method for row in matches))

    def test_reviewed_toponym_requires_matching_chain_and_does_not_move_pin(self):
        event = self.event("Farallon Islands", latitude=0.05, country="OTHER")
        key = ("OTHER", "CALIFORNIA", "FARALLON ISLANDS")
        review = {"coast_id": "TEST", "max_distance_km": 10, "source_url": "https://example.org/", "note": "Trecho de referência."}
        result = self.assignments([event], {key: review})[0]
        self.assertEqual(result.method, "reviewed_toponym")
        self.assertEqual(result.source, review["source_url"])
        self.assertAlmostEqual(result.distance, 5.56, places=2)
        self.assertEqual(self.assignments([event], {key: {**review, "coast_id": "WRONG"}})[0].status, "country_mismatch")

    def test_unknown_toponym_remains_eligible_under_direct_rule(self):
        result = self.assignments([self.event("", latitude=0.05)])[0]
        self.assertEqual(result.method, "direct_geocode")


if __name__ == "__main__":
    unittest.main()
