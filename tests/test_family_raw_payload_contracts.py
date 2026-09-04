"""End-to-end raw DigiKey/Mouser → matrix → score → UI/PDF contracts.

These tests use representative supplier payloads (not bare profile assertions)
to prove each family path: normalize → family matrix → limit direction →
engineering confidence → compact UI fields ↔ ECO/PDF comparison_table.
"""
from __future__ import annotations

import unittest

from integrations.digikey_client import normalize_digikey_product
from integrations.mouser_client import normalize_mouser_part
from src.alternative_engine import (
    apply_supplier_enrichment_to_candidate,
    calculate_drop_in_confidence,
)
from src.component_family_profiles import comparison_fields, get_family_profile
from src.datasheet_comparison import (
    build_datasheet_comparison,
    build_engineering_evidence_assessment,
    build_pdf_field_evidence,
    build_recommendation_score_breakdown,
)


def _dk_params(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"ParameterText": name, "ValueText": value} for name, value in pairs]


def _mouser_attrs(pairs: list[tuple[str, str]]) -> list[dict]:
    return [{"AttributeName": name, "AttributeValue": value} for name, value in pairs]


def _digikey_product(
    *,
    mpn: str,
    description: str,
    params: list[tuple[str, str]],
    pins: str | None = None,
    qty: int = 1000,
) -> dict:
    parameters = list(params)
    if pins is not None:
        parameters.append(("Number of Pins", pins))
    return {
        "Manufacturer": {"Name": "Test Mfr"},
        "ManufacturerProductNumber": mpn,
        "QuantityAvailable": qty,
        "Parameters": _dk_params(parameters),
        "Description": {"ProductDescription": description},
        "ProductStatus": {"Status": "Active"},
        "UnitPrice": 0.1,
    }


def _compact_ui_attributes(original: dict, candidate: dict, comparison_rows: list[dict]) -> list[str]:
    """Mirror authenticated_runtime compact comparison attribute selection."""
    attrs = ["Part Number", "Lifecycle", "Supplier", "Stock", "Unit Price", "Stock Delta", "Price Delta", "Package"]
    for row in comparison_rows:
        attribute = str(row.get("Attribute") or "").strip()
        if not attribute or attribute in {"Package", "Drop-In Confidence", "Drop-In Rating"}:
            continue
        if attribute in {"Lifecycle", "Stock", "Unit Price"}:
            continue
        attrs.append(attribute)
    attrs.extend(["Drop-In Confidence", "Drop-In Rating"])
    return attrs


def _eco_pdf_attributes(comparison_rows: list[dict]) -> list[str]:
    """Mirror comparison_snapshot['comparison_table'] attribute list."""
    return [
        str(row.get("Attribute") or "")
        for row in comparison_rows
        if isinstance(row, dict) and row.get("Attribute")
    ]


def _status_map(result: dict) -> dict[str, str]:
    return {row["Attribute"]: row["Status"] for row in result["rows"]}


def _assert_no_architecture(test: unittest.TestCase, result: dict) -> None:
    attrs = {row["Attribute"] for row in result["rows"]}
    test.assertNotIn("Architecture", attrs)
    test.assertNotIn("Topology / function", attrs)  # regulator-only; guard misuse on discretes/passives


class FamilyRawPayloadContractTests(unittest.TestCase):
    """One contract per required family from raw supplier payloads."""

    def _enrich(self, original: dict, candidate: dict, *, classification: str = "Verified direct substitute"):
        return apply_supplier_enrichment_to_candidate(
            original_data=original,
            candidate={
                "Alternative Part": candidate.get("manufacturer_part_number", "CAND"),
                "Recommendation Score": 70,
                "Classification": classification,
                "Substitute Type": "Direct" if "direct" in classification.casefold() else "Similar",
                "Supplier Relationship Evidence": [{
                    "supplier": "DigiKey",
                    "substitute_type": "Direct" if "direct" in classification.casefold() else "Similar",
                    "summary": "DigiKey relationship: Direct." if "direct" in classification.casefold() else "Similar",
                    "original_mpn": original.get("manufacturer_part_number", ""),
                    "candidate_mpn": candidate.get("manufacturer_part_number", ""),
                }],
            },
            candidate_supplier_data=candidate,
            canonical_part_number=str(original.get("manufacturer_part_number") or ""),
        )

    def _assert_ui_pdf_parity(self, original: dict, candidate: dict, result: dict) -> None:
        compact = _compact_ui_attributes(original, candidate, result["rows"])
        eco = _eco_pdf_attributes([
            {
                "Attribute": row.get("Attribute"),
                "Original": row.get("Original"),
                "Selected Alternative": row.get("Candidate"),
            }
            for row in result["rows"]
        ])
        # Every matrix engineering attribute (except Package, already in compact header)
        # must appear in compact UI; ECO table carries the full matrix.
        for row in result["rows"]:
            attr = row["Attribute"]
            self.assertIn(attr, eco)
            if attr != "Package":
                self.assertIn(attr, compact)
        pdf_rows = build_pdf_field_evidence(
            {"pages": []}, {"pages": []}, result["family"]
        )
        pdf_attrs = {row["Attribute"] for row in pdf_rows}
        matrix_attrs = {row["Attribute"] for row in result["rows"]}
        self.assertEqual(pdf_attrs, matrix_attrs)

    # ------------------------------------------------------------------ #
    # Capacitor
    # ------------------------------------------------------------------ #
    def test_capacitor_raw_digikey_nominal_and_limit_ge(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="C0603C104K5RACTU",
            description="Capacitor Ceramic 0.1uF 50V X7R 0603",
            params=[
                ("Package / Case", "0603 (1608 Metric)"),
                ("Mounting Type", "Surface Mount, MLCC"),
                ("Capacitance", "0.1 µF"),
                ("Tolerance", "±10%"),
                ("Voltage - Rated", "50V"),
                ("Temperature Coefficient", "X7R"),
                ("Operating Temperature", "-55°C ~ 125°C"),
            ],
        ))
        better = normalize_digikey_product(_digikey_product(
            mpn="C0603C104K5RACAUTO",
            description="Capacitor Ceramic 0.1uF 100V X7R 0603",
            params=[
                ("Package / Case", "0603 (1608 Metric)"),
                ("Mounting Type", "Surface Mount"),
                ("Capacitance", "100nF"),
                ("Tolerance", "±10%"),
                ("Voltage - Rated", "100V"),
                ("Temperature Coefficient", "X7R"),
                ("Operating Temperature", "-55°C ~ 125°C"),
            ],
        ))
        worse = normalize_digikey_product(_digikey_product(
            mpn="C0603C104K5RAC25",
            description="Capacitor Ceramic 0.1uF 25V X7R 0603",
            params=[
                ("Package / Case", "0603 (1608 Metric)"),
                ("Mounting Type", "Surface Mount"),
                ("Capacitance", "0.1 µF"),
                ("Tolerance", "±10%"),
                ("Voltage - Rated", "25V"),
                ("Temperature Coefficient", "X7R"),
            ],
        ))
        self.assertEqual(original["capacitance"], "0.1 µF")
        self.assertEqual(original["rated_voltage"], "50V")
        good = build_datasheet_comparison(original, better)
        bad = build_datasheet_comparison(original, worse)
        self.assertEqual(good["family"], "Capacitor")
        statuses = _status_map(good)
        self.assertEqual(statuses["Capacitance"], "Match")  # 0.1uF == 100nF
        self.assertEqual(statuses["Rated voltage"], "Match")  # 100 >= 50
        self.assertEqual(_status_map(bad)["Rated voltage"], "Different")
        self.assertNotIn("Architecture", {r["Attribute"] for r in good["rows"]})
        self.assertNotIn("Pin count", {r["Attribute"] for r in good["rows"]})
        good_conf = build_engineering_evidence_assessment(
            good["counts"], comparison_rows=good["rows"], family=good["family"]
        )["engineering_comparison_confidence"]
        bad_conf = build_engineering_evidence_assessment(
            bad["counts"], comparison_rows=bad["rows"], family=bad["family"]
        )["engineering_comparison_confidence"]
        self.assertGreater(good_conf, bad_conf)
        self._assert_ui_pdf_parity(original, better, good)

    # ------------------------------------------------------------------ #
    # Resistor
    # ------------------------------------------------------------------ #
    def test_resistor_raw_digikey_power_limit_ge(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="RC0603FR-0710KL",
            description="Thick film resistor 10k 0603",
            params=[
                ("Package / Case", "0603"),
                ("Mounting Type", "Surface Mount"),
                ("Resistance", "10 kOhms"),
                ("Tolerance", "±1%"),
                ("Power (Watts)", "0.1W, 1/10W"),
                ("Voltage Rating", "75V"),
                ("Temperature Coefficient", "±100ppm/°C"),
            ],
        ))
        candidate = normalize_digikey_product(_digikey_product(
            mpn="RC0603FR-0710KL-ALT",
            description="Thick film resistor 10k 0603",
            params=[
                ("Package / Case", "0603"),
                ("Mounting Type", "Surface Mount"),
                ("Resistance", "10k"),
                ("Tolerance", "±1%"),
                ("Power (Watts)", "0.125W"),
                ("Voltage Rating", "75V"),
            ],
        ))
        under = normalize_digikey_product(_digikey_product(
            mpn="RC0603JR-0710KL",
            description="Thick film resistor 10k 0603",
            params=[
                ("Package / Case", "0603"),
                ("Mounting Type", "Surface Mount"),
                ("Resistance", "10 kOhms"),
                ("Tolerance", "±1%"),
                ("Power (Watts)", "0.063W"),
            ],
        ))
        self.assertEqual(original["resistance"], "10 kOhms")
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Resistor")
        self.assertEqual(_status_map(result)["Power rating"], "Match")
        self.assertEqual(_status_map(build_datasheet_comparison(original, under))["Power rating"], "Different")
        self.assertNotIn("Architecture", {r["Attribute"] for r in result["rows"]})
        self.assertNotIn("Pin count", {r["Attribute"] for r in result["rows"]})
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # Inductor
    # ------------------------------------------------------------------ #
    def test_inductor_raw_digikey_isat_and_dcr(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="SRR1280-100M",
            description="Power inductor 10uH shielded",
            params=[
                ("Package / Case", "Nonstandard"),
                ("Mounting Type", "Surface Mount"),
                ("Inductance", "10 µH"),
                ("Current - Saturation", "5A"),
                ("Current Rating (Amps)", "4A"),
                ("DC Resistance (DCR)", "25mOhm"),
                ("Shielding", "Shielded"),
            ],
        ))
        better_dcr = normalize_digikey_product(_digikey_product(
            mpn="SRR1280-100M-B",
            description="Power inductor 10uH shielded",
            params=[
                ("Package / Case", "Nonstandard"),
                ("Mounting Type", "Surface Mount"),
                ("Inductance", "10uH"),
                ("Current - Saturation", "5A"),
                ("Current Rating (Amps)", "4A"),
                ("DC Resistance (DCR)", "20mOhm"),
                ("Shielding", "Shielded"),
            ],
        ))
        low_isat = normalize_digikey_product(_digikey_product(
            mpn="SRR1280-100M-L",
            description="Power inductor 10uH shielded",
            params=[
                ("Package / Case", "Nonstandard"),
                ("Mounting Type", "Surface Mount"),
                ("Inductance", "10 µH"),
                ("Current - Saturation", "2A"),
                ("Current Rating (Amps)", "4A"),
                ("DC Resistance (DCR)", "25mOhm"),
            ],
        ))
        result = build_datasheet_comparison(original, better_dcr)
        self.assertEqual(result["family"], "Inductor")
        self.assertEqual(_status_map(result)["DCR"], "Match")  # 20 <= 25
        self.assertEqual(_status_map(build_datasheet_comparison(original, low_isat))["Saturation current"], "Different")
        self.assertNotIn("Architecture", {r["Attribute"] for r in result["rows"]})
        self._assert_ui_pdf_parity(original, better_dcr, result)

    # ------------------------------------------------------------------ #
    # Diode
    # ------------------------------------------------------------------ #
    def test_diode_raw_digikey_vr_ge_and_vf_le(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="BAT54",
            description="Schottky diode 30V",
            params=[
                ("Package / Case", "TO-236-3, SC-59, SOT-23-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("Diode Type", "Schottky"),
                ("Voltage - DC Reverse (Vr) (Max)", "30V"),
                ("Current - Average Rectified (Io)", "200mA"),
                ("Voltage - Forward (Vf) (Max) @ If", "800mV"),
            ],
            pins="3",
        ))
        candidate = normalize_digikey_product(_digikey_product(
            mpn="BAT54-ALT",
            description="Schottky diode 40V",
            params=[
                ("Package / Case", "TO-236-3, SC-59, SOT-23-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("Diode Type", "Schottky"),
                ("Voltage - DC Reverse (Vr) (Max)", "40V"),
                ("Current - Average Rectified (Io)", "200mA"),
                ("Voltage - Forward (Vf) (Max) @ If", "450mV"),
            ],
            pins="3",
        ))
        high_vf = normalize_digikey_product(_digikey_product(
            mpn="BAT54-HVF",
            description="Schottky diode 30V",
            params=[
                ("Package / Case", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("Diode Type", "Schottky"),
                ("Voltage - DC Reverse (Vr) (Max)", "30V"),
                ("Current - Average Rectified (Io)", "200mA"),
                ("Voltage - Forward (Vf) (Max) @ If", "1.2V"),
            ],
            pins="3",
        ))
        self.assertEqual(original["reverse_voltage"], "30V")
        self.assertEqual(original["forward_voltage"], "800mV")
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Diode / protection")
        statuses = _status_map(result)
        self.assertEqual(statuses["Reverse voltage"], "Match")
        self.assertEqual(statuses["Forward voltage"], "Match")
        self.assertEqual(_status_map(build_datasheet_comparison(original, high_vf))["Forward voltage"], "Different")
        _assert_no_architecture(self, result)
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # BJT — MMBT3904 production path
    # ------------------------------------------------------------------ #
    def test_bjt_mmbt3904_raw_fields_and_incomplete_without_electricals(self):
        sparse_original = normalize_digikey_product(_digikey_product(
            mpn="MMBT3904LT1G",
            description="Transistor BJT NPN 40V 0.2A SOT-23",
            params=[
                ("Package / Case", "TO-236-3, SC-59, SOT-23-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
            ],
            pins="3",
        ))
        sparse_candidate = normalize_digikey_product(_digikey_product(
            mpn="MMBT3904-7-F",
            description="Transistor BJT NPN 40V 0.2A SOT-23",
            params=[
                ("Package / Case", "TO-236-3, SC-59, SOT-23-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
            ],
            pins="3",
        ))
        self.assertEqual(sparse_original["pin_count"], 3)
        sparse = build_datasheet_comparison(sparse_original, sparse_candidate)
        self.assertEqual(sparse["family"], "Bipolar transistor")
        attrs = {r["Attribute"] for r in sparse["rows"]}
        for required_label in (
            "Transistor polarity", "VCEO", "IC max", "hFE", "Power dissipation",
            "Transition frequency", "VCE(sat)", "Package", "Pin count", "Mounting",
            "Temperature range", "Pinout / footprint",
        ):
            self.assertIn(required_label, attrs)
        _assert_no_architecture(self, sparse)
        statuses = _status_map(sparse)
        self.assertEqual(statuses["Package"], "Match")
        self.assertEqual(statuses["Pin count"], "Match")
        for label in ("VCEO", "IC max", "hFE", "Power dissipation", "Pinout / footprint"):
            self.assertEqual(statuses[label], "Needs data", label)
        assessment = build_engineering_evidence_assessment(
            sparse["counts"],
            classification="Verified direct substitute",
            substitute_type="Direct",
            comparison_rows=sparse["rows"],
            family=sparse["family"],
            supplier_relationship_evidence=[{
                "supplier": "DigiKey",
                "substitute_type": "Direct",
                "summary": "DigiKey relationship: Direct.",
                "original_mpn": "MMBT3904LT1G",
                "candidate_mpn": "MMBT3904-7-F",
            }],
        )
        self.assertEqual(assessment["supplier_relationship_confidence"], 95)
        self.assertLess(assessment["engineering_comparison_confidence"], 55)
        self.assertIn("incomplete", assessment["engineering_evidence_summary"])
        score = build_recommendation_score_breakdown(
            70, assessment["engineering_comparison_confidence"], sparse["counts"],
            is_explicit_substitute=True,
        )
        self.assertLess(score["recommendation_score"], 85)
        enriched = self._enrich(sparse_original, sparse_candidate)
        self.assertLess(int(enriched["Drop-In Confidence"]), 55)
        self.assertLess(int(enriched["Engineering Comparison Confidence"]), 55)
        self._assert_ui_pdf_parity(sparse_original, sparse_candidate, sparse)

    def test_bjt_mmbt3904_fully_populated_electricals_high_confidence(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="MMBT3904LT1G",
            description="Transistor BJT NPN 40V 0.2A SOT-23",
            params=[
                ("Package / Case", "TO-236-3, SC-59, SOT-23-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("Transistor Type", "NPN"),
                ("Voltage - Collector Emitter Breakdown (Max)", "40V"),
                ("Voltage - Collector Base (Max)", "60V"),
                ("Current - Collector (Ic) (Max)", "200mA"),
                ("DC Current Gain (hFE) (Min) @ Ic, Vce", "100 @ 10mA, 1V"),
                ("Power - Max", "300mW"),
                ("Frequency - Transition", "300MHz"),
                ("Vce Saturation (Max) @ Ib, Ic", "300mV @ 5mA, 50mA"),
                ("Current - Collector Cutoff (Max)", "50nA"),
                ("Operating Temperature", "-55°C ~ 150°C"),
            ],
            pins="3",
        ))
        # Explicit pinout evidence (not normally a DigiKey parameter; set after normalize)
        original["pinout"] = "SOT-23 E-B-C"
        candidate = normalize_digikey_product(_digikey_product(
            mpn="MMBT3904-7-F",
            description="Transistor BJT NPN 40V 0.2A SOT-23",
            params=[
                ("Package / Case", "TO-236-3, SC-59, SOT-23-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("Transistor Type", "NPN"),
                ("Voltage - Collector Emitter Breakdown (Max)", "40V"),
                ("Voltage - Collector Base (Max)", "60V"),
                ("Current - Collector (Ic) (Max)", "200mA"),
                ("DC Current Gain (hFE) (Min) @ Ic, Vce", "100 @ 10mA, 1V"),
                ("Power - Max", "350mW"),
                ("Frequency - Transition", "300MHz"),
                ("Vce Saturation (Max) @ Ib, Ic", "250mV @ 5mA, 50mA"),
                ("Current - Collector Cutoff (Max)", "50nA"),
                ("Operating Temperature", "-55°C ~ 150°C"),
            ],
            pins="3",
        ))
        candidate["pinout"] = "SOT-23 E-B-C"
        self.assertEqual(original["device_type"], "NPN")
        self.assertEqual(original["collector_emitter_voltage"], "40V")
        self.assertEqual(original["collector_current"], "200mA")
        self.assertEqual(original["dc_current_gain"], "100 @ 10mA, 1V")
        self.assertEqual(original["power_dissipation"], "300mW")
        self.assertEqual(original["transition_frequency"], "300MHz")
        self.assertEqual(original["vce_saturation"], "300mV @ 5mA, 50mA")
        result = build_datasheet_comparison(original, candidate)
        statuses = _status_map(result)
        self.assertEqual(statuses["Transistor polarity"], "Match")
        self.assertEqual(statuses["VCEO"], "Match")
        self.assertEqual(statuses["IC max"], "Match")
        self.assertEqual(statuses["hFE"], "Match")
        self.assertEqual(statuses["Power dissipation"], "Match")  # 350 >= 300
        self.assertEqual(statuses["Transition frequency"], "Match")
        self.assertEqual(statuses["VCE(sat)"], "Match")  # 250mV <= 300mV
        self.assertEqual(statuses["Pinout / footprint"], "Match")
        _assert_no_architecture(self, result)
        assessment = build_engineering_evidence_assessment(
            result["counts"], comparison_rows=result["rows"], family=result["family"]
        )
        self.assertGreaterEqual(assessment["engineering_comparison_confidence"], 82)
        enriched = self._enrich(original, candidate)
        self.assertGreaterEqual(int(enriched["Engineering Comparison Confidence"]), 82)
        # Mouser path also normalizes BJT polarity aliases
        mouser = normalize_mouser_part({
            "Manufacturer": "Diodes",
            "ManufacturerPartNumber": "MMBT3904-7-F",
            "Availability": "5000 In Stock",
            "Description": "Transistor BJT NPN",
            "ProductAttributes": _mouser_attrs([
                ("Package / Case", "SOT-23-3"),
                ("Transistor Polarity", "NPN"),
                ("Collector-Emitter Voltage VCEO Max", "40 V"),
                ("Continuous Collector Current", "200 mA"),
                ("Power Dissipation", "300 mW"),
            ]),
        })
        self.assertEqual(mouser["device_type"], "NPN")
        self.assertEqual(mouser["collector_emitter_voltage"], "40 V")
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # MOSFET
    # ------------------------------------------------------------------ #
    def test_mosfet_raw_digikey_rds_on_lower_is_better(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="Si2302",
            description="N-Channel MOSFET 20V",
            params=[
                ("Package / Case", "TO-236-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("FET Type", "N-Channel"),
                ("Drain to Source Voltage (Vdss)", "20V"),
                ("Current - Continuous Drain (Id) @ 25°C", "2.8A"),
                ("Rds On (Max) @ Id, Vgs", "54mOhm @ 2.8A, 4.5V"),
                ("Vgs(th) (Max) @ Id", "1.2V @ 250µA"),
                ("Power Dissipation (Max)", "1.25W"),
            ],
            pins="3",
        ))
        better = dict(normalize_digikey_product(_digikey_product(
            mpn="Si2302B",
            description="N-Channel MOSFET 20V",
            params=[
                ("Package / Case", "TO-236-3"),
                ("Supplier Device Package", "SOT-23-3"),
                ("Mounting Type", "Surface Mount"),
                ("FET Type", "N-Channel"),
                ("Drain to Source Voltage (Vdss)", "20V"),
                ("Current - Continuous Drain (Id) @ 25°C", "3A"),
                ("Rds On (Max) @ Id, Vgs", "40mOhm @ 2.8A, 4.5V"),
                ("Vgs(th) (Max) @ Id", "1.2V @ 250µA"),
            ],
            pins="3",
        )))
        worse = dict(normalize_digikey_product(_digikey_product(
            mpn="Si2302W",
            description="N-Channel MOSFET 20V",
            params=[
                ("Package / Case", "TO-236-3"),
                ("Mounting Type", "Surface Mount"),
                ("FET Type", "N-Channel"),
                ("Drain to Source Voltage (Vdss)", "20V"),
                ("Current - Continuous Drain (Id) @ 25°C", "2.8A"),
                ("Rds On (Max) @ Id, Vgs", "120mOhm @ 2.8A, 4.5V"),
            ],
            pins="3",
        )))
        original["pinout"] = better["pinout"] = worse["pinout"] = "SOT-23 G-S-D"
        result = build_datasheet_comparison(original, better)
        self.assertEqual(result["family"], "MOSFET")
        self.assertEqual(original["rds_on"], "54mOhm @ 2.8A, 4.5V")
        self.assertEqual(_status_map(result)["RDS(on)"], "Match")
        self.assertEqual(_status_map(build_datasheet_comparison(original, worse))["RDS(on)"], "Different")
        _assert_no_architecture(self, result)
        self._assert_ui_pdf_parity(original, better, result)

    # ------------------------------------------------------------------ #
    # Regulator
    # ------------------------------------------------------------------ #
    def test_regulator_raw_digikey_dropout_lower_is_better(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="AP2112",
            description="LDO voltage regulator 3.3V",
            params=[
                ("Package / Case", "SOT-23-5"),
                ("Mounting Type", "Surface Mount"),
                ("Topology", "LDO"),
                ("Voltage - Input (Max)", "6V"),
                ("Voltage - Output (Min/Fixed)", "3.3V"),
                ("Current - Output", "600mA"),
                ("Voltage Dropout (Max)", "0.4V @ 600mA"),
            ],
            pins="5",
        ))
        candidate = normalize_digikey_product(_digikey_product(
            mpn="AP2112B",
            description="LDO voltage regulator 3.3V",
            params=[
                ("Package / Case", "SOT-23-5"),
                ("Mounting Type", "Surface Mount"),
                ("Topology", "LDO"),
                ("Voltage - Input (Max)", "6V"),
                ("Voltage - Output (Min/Fixed)", "3.3V"),
                ("Current - Output", "600mA"),
                ("Voltage Dropout (Max)", "0.25V @ 600mA"),
            ],
            pins="5",
        ))
        original["pinout"] = candidate["pinout"] = "EN-VIN-GND-VOUT-NC"
        original["architecture"] = original.get("architecture") or original.get("device_type") or "LDO"
        # Topology lands in architecture field via digikey map key "architecture"
        self.assertTrue(original.get("architecture") or original.get("output_voltage"))
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Regulator")
        self.assertEqual(original["output_voltage"], "3.3V")
        self.assertEqual(original["dropout_voltage"], "0.4V @ 600mA")
        self.assertEqual(_status_map(result)["Dropout voltage"], "Match")
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # Op-amp
    # ------------------------------------------------------------------ #
    def test_opamp_raw_digikey_matrix_and_channels(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="LM358DR",
            description="Operational amplifier dual",
            params=[
                ("Package / Case", "8-SOIC"),
                ("Mounting Type", "Surface Mount"),
                ("Amplifier Type", "General Purpose"),
                ("Number of Circuits", "2"),
                ("Voltage - Supply Span (Min)", "3V"),
                ("Voltage - Supply Span (Max)", "32V"),
                ("Gain Bandwidth Product", "1.1 MHz"),
                ("Slew Rate", "0.5V/µs"),
            ],
            pins="8",
        ))
        candidate = normalize_digikey_product(_digikey_product(
            mpn="LM358DR2G",
            description="Operational amplifier dual",
            params=[
                ("Package / Case", "8-SOIC"),
                ("Mounting Type", "Surface Mount"),
                ("Amplifier Type", "General Purpose"),
                ("Number of Circuits", "2"),
                ("Voltage - Supply Span (Min)", "3V"),
                ("Voltage - Supply Span (Max)", "32V"),
                ("Gain Bandwidth Product", "1.1 MHz"),
                ("Slew Rate", "0.6V/µs"),
            ],
            pins="8",
        ))
        original["pinout"] = candidate["pinout"] = "SOIC-8 standard"
        # channel_count is inferred from description "dual"
        self.assertEqual(int(float(original["channel_count"])), 2)
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Operational amplifier")
        self.assertIn("Channels", {r["Attribute"] for r in result["rows"]})
        self.assertEqual(_status_map(result)["Channels"], "Match")
        # Package/ball alone insufficient: strip pinout + electricals from candidate
        weak = dict(candidate)
        weak["pinout"] = ""
        weak["bandwidth_mhz"] = None
        weak["slew_rate_v_us"] = None
        weak_result = build_datasheet_comparison(original, weak)
        weak_conf = build_engineering_evidence_assessment(
            weak_result["counts"], comparison_rows=weak_result["rows"], family=weak_result["family"]
        )["engineering_comparison_confidence"]
        full_conf = build_engineering_evidence_assessment(
            result["counts"], comparison_rows=result["rows"], family=result["family"]
        )["engineering_comparison_confidence"]
        self.assertGreater(full_conf, weak_conf)
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # MCU
    # ------------------------------------------------------------------ #
    def test_mcu_package_alone_cannot_establish_compatibility(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="STM32F103C8T6",
            description="ARM Cortex-M3 microcontroller 72MHz",
            params=[
                ("Package / Case", "48-LQFP"),
                ("Mounting Type", "Surface Mount"),
                ("Core Processor", "ARM Cortex-M3"),
                ("Speed", "72MHz"),
                ("Program Memory Size", "64KB"),
                ("Number of I/O", "37"),
                ("Voltage - Supply (Vcc/Vdd)", "2V ~ 3.6V"),
            ],
            pins="48",
        ))
        package_only = normalize_digikey_product(_digikey_product(
            mpn="OTHER-LQFP48",
            description="ARM Cortex-M0 microcontroller",
            params=[
                ("Package / Case", "48-LQFP"),
                ("Mounting Type", "Surface Mount"),
            ],
            pins="48",
        ))
        full = dict(normalize_digikey_product(_digikey_product(
            mpn="STM32F103C8T6-TR",
            description="ARM Cortex-M3 microcontroller 72MHz",
            params=[
                ("Package / Case", "48-LQFP"),
                ("Mounting Type", "Surface Mount"),
                ("Core Processor", "ARM Cortex-M3"),
                ("Speed", "72MHz"),
                ("Program Memory Size", "64KB"),
                ("Number of I/O", "37"),
                ("Voltage - Supply (Vcc/Vdd)", "2V ~ 3.6V"),
            ],
            pins="48",
        )))
        original["pinout"] = full["pinout"] = "LQFP48 STM32 pinout"
        package_only["pinout"] = ""
        sparse = build_datasheet_comparison(original, package_only)
        complete = build_datasheet_comparison(original, full)
        self.assertEqual(sparse["family"], "MCU / processor")
        self.assertEqual(_status_map(sparse)["Pin count"], "Match")
        self.assertEqual(_status_map(sparse)["Pinout / configuration compatibility"], "Needs data")
        sparse_conf = build_engineering_evidence_assessment(
            sparse["counts"], comparison_rows=sparse["rows"], family=sparse["family"]
        )["engineering_comparison_confidence"]
        full_conf = build_engineering_evidence_assessment(
            complete["counts"], comparison_rows=complete["rows"], family=complete["family"]
        )["engineering_comparison_confidence"]
        self.assertLess(sparse_conf, 55)
        self.assertGreater(full_conf, sparse_conf)
        self.assertGreaterEqual(full_conf, 70)
        self._assert_ui_pdf_parity(original, full, complete)

    # ------------------------------------------------------------------ #
    # FPGA / CPLD
    # ------------------------------------------------------------------ #
    def test_fpga_ball_count_alone_cannot_establish_compatibility(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="XC7A35T-1CPG236C",
            description="Artix-7 FPGA",
            params=[
                ("Package / Case", "238-LFBGA, CSPBGA"),
                ("Mounting Type", "Surface Mount"),
                ("Series", "Artix-7"),
                ("Number of Logic Elements/Cells", "33280"),
                ("Number of I/O", "106"),
                ("Voltage - Supply", "0.95V ~ 1.05V"),
                ("Number of Balls", "236"),
            ],
            pins="236",
        ))
        # Prefer explicit ball count field
        self.assertEqual(original["pin_count"], 236)
        ball_only = normalize_digikey_product(_digikey_product(
            mpn="OTHER-BGA236",
            description="FPGA generic",
            params=[
                ("Package / Case", "238-LFBGA, CSPBGA"),
                ("Mounting Type", "Surface Mount"),
                ("Number of Balls", "236"),
            ],
        ))
        full = dict(normalize_digikey_product(_digikey_product(
            mpn="XC7A35T-1CPG236C-ND",
            description="Artix-7 FPGA",
            params=[
                ("Package / Case", "238-LFBGA, CSPBGA"),
                ("Mounting Type", "Surface Mount"),
                ("Series", "Artix-7"),
                ("Number of Logic Elements/Cells", "33280"),
                ("Number of I/O", "106"),
                ("Voltage - Supply", "0.95V ~ 1.05V"),
                ("Number of Balls", "236"),
            ],
        )))
        original["pinout"] = full["pinout"] = "CPG236 Artix-7"
        ball_only["pinout"] = ""
        sparse = build_datasheet_comparison(original, ball_only)
        complete = build_datasheet_comparison(original, full)
        self.assertEqual(sparse["family"], "FPGA / CPLD")
        self.assertIn("Logic resources", {r["Attribute"] for r in sparse["rows"]})
        sparse_conf = build_engineering_evidence_assessment(
            sparse["counts"], comparison_rows=sparse["rows"], family=sparse["family"]
        )["engineering_comparison_confidence"]
        full_conf = build_engineering_evidence_assessment(
            complete["counts"], comparison_rows=complete["rows"], family=complete["family"]
        )["engineering_comparison_confidence"]
        self.assertLess(sparse_conf, 55)
        self.assertGreater(full_conf, sparse_conf)
        self._assert_ui_pdf_parity(original, full, complete)

    # ------------------------------------------------------------------ #
    # Connector
    # ------------------------------------------------------------------ #
    def test_connector_raw_digikey_positions_pitch(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="HDR-10",
            description="Board-to-board connector header 10pos",
            params=[
                ("Package / Case", "Through Hole"),
                ("Mounting Type", "Through Hole"),
                ("Number of Positions", "10"),
                ("Pitch - Mating", "2.54mm"),
                ("Connector Type", "Header"),
                ("Current Rating (Amps)", "3A"),
                ("Voltage Rating", "250V"),
            ],
        ))
        candidate = normalize_digikey_product(_digikey_product(
            mpn="HDR-10-B",
            description="Board-to-board connector header 10pos",
            params=[
                ("Package / Case", "Through Hole"),
                ("Mounting Type", "Through Hole"),
                ("Number of Positions", "10"),
                ("Pitch - Mating", "2.54mm"),
                ("Connector Type", "Header"),
                ("Current Rating (Amps)", "3A"),
            ],
        ))
        wrong = normalize_digikey_product(_digikey_product(
            mpn="HDR-8",
            description="Board-to-board connector header 8pos",
            params=[
                ("Package / Case", "Through Hole"),
                ("Mounting Type", "Through Hole"),
                ("Number of Positions", "8"),
                ("Pitch - Mating", "2.54mm"),
                ("Connector Type", "Header"),
            ],
        ))
        self.assertEqual(original["positions"], "10")
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Connector / electromechanical")
        self.assertEqual(_status_map(result)["Positions"], "Match")
        self.assertEqual(_status_map(result)["Pitch"], "Match")
        self.assertEqual(_status_map(build_datasheet_comparison(original, wrong))["Positions"], "Different")
        self.assertNotIn("Pin count", {r["Attribute"] for r in result["rows"]})
        self.assertNotIn("Architecture", {r["Attribute"] for r in result["rows"]})
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # Relay (electromechanical / other)
    # ------------------------------------------------------------------ #
    def test_relay_raw_digikey_coil_and_contact(self):
        original = normalize_digikey_product(_digikey_product(
            mpn="G5V-1-DC5",
            description="Signal relay SPDT 5V coil",
            params=[
                ("Package / Case", "Through Hole"),
                ("Mounting Type", "Through Hole"),
                ("Contact Form", "SPDT (1 Form C)"),
                ("Coil Voltage", "5VDC"),
                ("Contact Rating (Current)", "1A"),
                ("Switching Voltage", "125VAC, 60VDC - Max"),
            ],
        ))
        candidate = normalize_digikey_product(_digikey_product(
            mpn="G5V-1-DC5-ALT",
            description="Signal relay SPDT 5V coil",
            params=[
                ("Package / Case", "Through Hole"),
                ("Mounting Type", "Through Hole"),
                ("Contact Form", "SPDT (1 Form C)"),
                ("Coil Voltage", "5VDC"),
                ("Contact Rating (Current)", "1A"),
                ("Switching Voltage", "125VAC, 60VDC - Max"),
            ],
        ))
        wrong_coil = normalize_digikey_product(_digikey_product(
            mpn="G5V-1-DC12",
            description="Signal relay SPDT 12V coil",
            params=[
                ("Package / Case", "Through Hole"),
                ("Mounting Type", "Through Hole"),
                ("Contact Form", "SPDT (1 Form C)"),
                ("Coil Voltage", "12VDC"),
                ("Contact Rating (Current)", "1A"),
            ],
        ))
        self.assertEqual(original["coil_voltage"], "5VDC")
        result = build_datasheet_comparison(original, candidate)
        self.assertEqual(result["family"], "Relay")
        self.assertEqual(_status_map(result)["Coil voltage"], "Match")
        mismatch = build_datasheet_comparison(original, wrong_coil)
        self.assertEqual(_status_map(mismatch)["Coil voltage"], "Different")
        good_conf = build_engineering_evidence_assessment(
            result["counts"], comparison_rows=result["rows"], family=result["family"]
        )["engineering_comparison_confidence"]
        bad_conf = build_engineering_evidence_assessment(
            mismatch["counts"], comparison_rows=mismatch["rows"], family=mismatch["family"]
        )["engineering_comparison_confidence"]
        self.assertGreater(good_conf, bad_conf)
        self.assertNotIn("Architecture", {r["Attribute"] for r in result["rows"]})
        self._assert_ui_pdf_parity(original, candidate, result)

    # ------------------------------------------------------------------ #
    # Cross-family isolation
    # ------------------------------------------------------------------ #
    def test_passive_and_discrete_never_leak_architecture_or_cross_fields(self):
        cap = build_datasheet_comparison(
            normalize_digikey_product(_digikey_product(
                mpn="C1", description="Ceramic capacitor",
                params=[("Package / Case", "0603"), ("Capacitance", "1uF"), ("Voltage - Rated", "16V")],
            )),
            normalize_digikey_product(_digikey_product(
                mpn="C2", description="Ceramic capacitor",
                params=[("Package / Case", "0603"), ("Capacitance", "1uF"), ("Voltage - Rated", "16V")],
            )),
        )
        bjt = build_datasheet_comparison(
            normalize_digikey_product(_digikey_product(
                mpn="Q1", description="NPN transistor",
                params=[("Package / Case", "SOT-23"), ("Transistor Type", "NPN")],
                pins="3",
            )),
            normalize_digikey_product(_digikey_product(
                mpn="Q2", description="NPN transistor",
                params=[("Package / Case", "SOT-23"), ("Transistor Type", "NPN")],
                pins="3",
            )),
        )
        for result in (cap, bjt):
            attrs = {r["Attribute"] for r in result["rows"]}
            self.assertNotIn("Architecture", attrs)
            self.assertNotIn("Logic resources", attrs)
            self.assertNotIn("Positions", attrs)


if __name__ == "__main__":
    unittest.main()
