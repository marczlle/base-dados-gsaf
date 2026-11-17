"""Verificações das decisões que podem excluir datas ou apagar registros."""
from datetime import date
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clean_data as cleaning


class CleaningRulesTest(unittest.TestCase):
    def test_locate_input_follows_archive_reorganization_and_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Old Data" / "Md"
            archive.mkdir(parents=True)
            source = archive / "GSAF_clima_lua.csv"
            source.write_text("header\n", encoding="utf-8")
            self.assertEqual(cleaning.locate_input(root), source)
            (root / source.name).write_text("other\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cleaning.locate_input(root)

    def test_months_are_explicit_and_bounded(self):
        for value in ["Sep", "September", "sept.", "Setembro", "9", "09", "9.0"]:
            self.assertEqual(cleaning.month_number(value), 9)
        self.assertIsNone(cleaning.month_number("septembrr"))
        self.assertIsNone(cleaning.month_number("13"))
        self.assertIsNone(cleaning.month_number("unknown"))

    def test_country_case_and_contextual_state_aliases(self):
        for country in ["MEXICO", "Mexico", "MeXICO"]:
            geo = cleaning.geography(dict(Country=country, State=" Quntana  Roo ", Location="Turtle   beach"))
            self.assertEqual(geo, dict(Country="MEXICO", State="QUINTANA ROO", Location="TURTLE BEACH"))
        geo = cleaning.geography(dict(Country="Brazil", State="São Paulo.", Location="unknown"))
        self.assertEqual(geo["State"], "SÃO PAULO")
        self.assertEqual(geo["Location"], "")
        # Não aplicar sigla de outro país.
        self.assertEqual(cleaning.geography(dict(Country="USA", State="WA", Location="x"))["State"], "WA")

    def test_coordinates_do_not_impute_or_flip_signs(self):
        self.assertEqual(cleaning.coordinate("-18,0833300", 90), ("-18.08333", "valid"))
        self.assertEqual(cleaning.coordinate("0", 90), ("0", "valid"))
        self.assertEqual(cleaning.coordinate("-0.000", 90), ("0", "valid"))
        self.assertEqual(cleaning.coordinate("unknown", 90), ("", "missing"))
        self.assertEqual(cleaning.coordinate("-91", 90), ("", "out_of_range"))
        self.assertEqual(cleaning.coordinate("Infinity", 180), ("", "non_finite"))
        self.assertEqual(cleaning.coordinate("1,234.50", 180), ("", "invalid_format"))

    def test_exact_and_ambiguous_legacy_dates(self):
        for text in ["24th May", "24-May-2026", "24 May 2026", "24-May--2026", "24-May-2026.a", "05/24/2026"]:
            parsed = cleaning.source_date(text, 2026)
            self.assertEqual(parsed["status"], "exact", text)
            self.assertEqual(parsed["dates"], [date(2026, 5, 24)], text)
        self.assertEqual(cleaning.source_date("27-Feb-25", 2025)["dates"], [date(2025, 2, 27)])
        parsed = cleaning.source_date("02/10/2025", 2025)
        self.assertEqual(parsed["status"], "ambiguous_numeric")
        self.assertEqual(len(parsed["dates"]), 2)
        self.assertEqual(cleaning.source_date("05/05/2025", 2025)["status"], "exact")

    def test_report_ranges_missing_and_conflicts_are_not_exact(self):
        for text, year, expected in [
            ("Reported 26-Jun-1972", 1972, "reported_date"),
            ("02-Feb-1959 Reported", 1959, "reported_date"),
            ("22nd-23rd March", 2026, "range_or_approximate"),
            ("02-Mar-1943 to 07-Mar-1943", 1943, "range_or_approximate"),
            ("Early Sep-2000", 2000, "range_or_approximate"),
            ("Nov-1999", 1999, "month_only"), ("1953", 1953, "year_only"),
            ("23-Oct-1962", 1982, "year_conflict"),
            ("10-Jul-202", 2020, "year_conflict"),
        ]:
            self.assertEqual(cleaning.source_date(text, year)["status"], expected, text)
        self.assertIsNone(cleaning.safe_date(2023, 2, 29))
        self.assertEqual(cleaning.safe_date(2024, 2, 29), date(2024, 2, 29))

    def test_unknown_day_never_becomes_day_one_or_fifteen(self):
        row = dict(Year="2004", Month="Aug", Day="unknown")
        self.assertEqual(cleaning.classify_date(row, [], date(2026, 10, 23)), ("day_unknown", ""))

    def test_source_disagreement_not_resolved_by_current_components(self):
        row = dict(Year="2025", Month="10", Day="2")
        source = {"_parsed": cleaning.source_date("02/10/2025", 2025)}
        self.assertEqual(cleaning.classify_date(row, [source], date(2026, 10, 23)), ("ambiguous_numeric", ""))
        row = dict(Year="2025", Month="May", Day="20")
        source = {"_parsed": cleaning.source_date("21-May-2025", 2025)}
        self.assertEqual(cleaning.classify_date(row, [source], date(2026, 10, 23)), ("source_date_conflict", ""))

    def test_reported_date_is_eligible_and_remains_distinguishable(self):
        row = dict(Year="1972", Month="Jun", Day="26")
        source = {"_parsed": cleaning.source_date("Reported 26-Jun-1972", 1972)}
        self.assertEqual(cleaning.classify_date(row, [source], date(2026, 10, 23)),
                         ("reported_date", "1972-06-26"))

    def test_reported_does_not_override_ambiguous_or_conflicting_dates(self):
        for text, year, month, day, expected in [
            ("Reported 02/10/2025", 2025, "Oct", "2", "ambiguous_numeric"),
            ("Reported 26-Jun-1971", 1972, "Jun", "26", "year_conflict"),
            ("Reported 26-Jun-1972", 1972, "Jun", "25", "source_date_conflict"),
            ("Reported 02-Mar-1943 to 07-Mar-1943", 1943, "Mar", "2", "range_or_approximate"),
        ]:
            source = {"_parsed": cleaning.source_date(text, year)}
            row = dict(Year=str(year), Month=month, Day=day)
            self.assertEqual(cleaning.classify_date(row, [source], date(2026, 10, 23)), (expected, ""))

    def test_shared_case_number_and_attributes_do_not_remove_victims(self):
        sources = [dict(_row=2, Name="Person A", Case="same"), dict(_row=3, Name="Person B", Case="same")]
        rows = [dict(_signature="sig", _sources=sources, source_csv_record=i,
                     duplicate_removed=0) for i in [2, 3]]
        evidence = cleaning.remove_confirmed_duplicates(rows, ["Name", "Case"])
        self.assertEqual(sum(r["duplicate_removed"] for r in rows), 0)
        self.assertEqual(evidence[0]["assessment"], "distinct_source_records")

    def test_identical_full_upstream_records_confirm_duplicate(self):
        sources = [dict(_row=2, Name="Person A", Case="same"), dict(_row=3, Name="Person A", Case="same")]
        rows = [dict(_signature="sig", _sources=sources, source_csv_record=i,
                     duplicate_removed=0) for i in [2, 3]]
        evidence = cleaning.remove_confirmed_duplicates(rows, ["Name", "Case"])
        self.assertEqual([r["duplicate_removed"] for r in rows], [0, 1])
        self.assertEqual(evidence[0]["removed_count"], 1)

    def test_local_days_count_events_and_expose_coordinate_disagreement(self):
        base = dict(eligible_local_day=1, location_id="loc1", date="2025-05-24",
                    Country="AUSTRALIA", State="QUEENSLAND", Location="REEF",
                    extracted_lat="-18", extracted_lon="146", date_status="exact")
        rows = [dict(base, record_id="a"), dict(base, record_id="b", extracted_lat="-19", date_status="reported_date")]
        days = cleaning.local_days(rows)
        self.assertEqual(len(days), 1)
        self.assertEqual(days[0]["attack"], 1)
        self.assertEqual(days[0]["attack_count"], 2)
        self.assertEqual(days[0]["exact_attack_count"], 1)
        self.assertEqual(days[0]["reported_attack_count"], 1)
        self.assertEqual(days[0]["has_reported_date"], 1)
        self.assertEqual(days[0]["coordinate_conflict"], 1)
        self.assertEqual(days[0]["extracted_lat"], "")

    def test_prepare_preserves_raw_values_and_separates_non_exact_dates(self):
        base = {field: "" for field in cleaning.RAW_FIELDS}
        base.update(Year="2025", Month="September", Day="unknown", Country="MeXICO",
                    State="Guerro", Location=" Playa   X ", Time="unknown", Activity="Swimming",
                    extracted_lat="0", extracted_lon="-90.5", moon_phase="Full Moon",
                    moon_illumination="0.9", temperature_2m_mean="23.5")
        legacy = {field: base[field] for field in ["Year", "Country", "State", "Location", "Time", "Activity"]}
        legacy.update(Date="Sep-2025", Name="Person A", Type="Unprovoked")
        prepared, _, _ = cleaning.prepare(list(base), [base], list(legacy), [legacy], date(2026, 10, 23))
        row = prepared[0]
        self.assertEqual(row["date"], "")
        self.assertEqual(row["Month"], 9)
        self.assertEqual(row["Day"], None)
        self.assertEqual(row["eligible_daily_event"], 0)
        self.assertEqual(row["extracted_lat"], "0")
        for field in cleaning.RAW_FIELDS:
            self.assertEqual(row[field + "_raw"], base[field])
        for field in cleaning.DERIVED:
            self.assertEqual(row[field], "")

    def test_prepare_reported_preserves_enrichment_and_excludes_no_valid_day(self):
        base = {field: "" for field in cleaning.RAW_FIELDS}
        base.update(Year="1972", Month="Jun", Day="26", Country="Australia",
                    State="Queensland", Location="Pancake Creek", Time="unknown", Activity="unknown",
                    extracted_lat="-24", extracted_lon="151", moon_phase="Full Moon",
                    moon_illumination="0.9", temperature_2m_mean="23.5")
        legacy = {field: base[field] for field in ["Year", "Country", "State", "Location", "Time", "Activity"]}
        legacy.update(Date="Reported 26-Jun-1972", Name="Person A", Type="Unprovoked")
        prepared, _, _ = cleaning.prepare(list(base), [base], list(legacy), [legacy], date(2026, 10, 23))
        row = prepared[0]
        self.assertEqual(row["date"], "1972-06-26")
        self.assertEqual(row["date_status"], "reported_date")
        self.assertEqual(row["date_is_approximate"], 1)
        self.assertEqual(row["eligible_daily_event"], 1)
        self.assertEqual(row["eligible_local_day"], 1)
        self.assertEqual(row["daily_exclusion_reasons"], "")
        for field in cleaning.DERIVED:
            self.assertEqual(row[field], base[field])

    def test_model_events_keeps_unnamed_and_missing_coordinates_without_post_event_fields(self):
        base = dict(record_id="a", date="2025-05-24", Country="", State="", Location="",
                    extracted_lat="-24", extracted_lon="151", date_is_approximate=0,
                    coordinate_status="valid_numeric_pair", coordinates_spatially_verified=0,
                    eligible_daily_event=1, eligible_local_day=0, Time="10h00", Species="White Shark",
                    Activity="Swimming", temperature_2m_mean="20")
        rows = [base, dict(base, record_id="b", extracted_lat="", extracted_lon="",
                           coordinate_status="missing_pair", date_is_approximate=1),
                dict(base, record_id="excluded", eligible_daily_event=0)]
        model = cleaning.model_events(rows)
        self.assertEqual([r["record_id"] for r in model], ["a", "b"])
        self.assertEqual([r["needs_geocoding"] for r in model], [0, 1])
        self.assertEqual(model[0]["location"], "")
        self.assertEqual(model[1]["date_is_approximate"], 1)
        self.assertEqual(set(model[0]), {
            "record_id", "date", "country", "state", "location", "latitude", "longitude",
            "date_is_approximate", "coordinate_status", "coordinates_spatially_verified", "needs_geocoding",
        })


if __name__ == "__main__":
    unittest.main()
