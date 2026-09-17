from __future__ import annotations

import importlib.metadata
import json
import runpy
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ValidationError

import opencnmv
from opencnmv.canonicalize.facts import fact_id, fact_key
from opencnmv.model.canonical import CanonicalFiling, VariantVersion
from opencnmv.serialize import canonical_bytes

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "g1/G1-E-canonical-model-freeze"
BUILDER = ROOT / "g2/G2-A-durable-canonical-core/g2a_rebuild.py"
FIXTURE_NAMES = {
    "ibe_fy2024.json",
    "bbva_fy2024.json",
    "san_fy2024.json",
    "tef_20484.json",
}


def build_in_memory() -> None:
    builder = runpy.run_path(str(BUILDER), run_name="frozen_core_builder")
    data = builder["load_inputs"]()
    fixtures = {
        "ibe_fy2024.json": builder["build_corpus_fixture"](data, "IBE", "FY2024"),
        "bbva_fy2024.json": builder["build_bbva"](data),
        "san_fy2024.json": builder["build_san"](data),
        "tef_20484.json": builder["build_tef"](data),
    }
    if builder["_NET_CALLS"]:
        raise RuntimeError("The frozen rebuild attempted network access")
    print(json.dumps({name: canonical_bytes(fx).decode("utf-8")
                      for name, fx in fixtures.items()}, ensure_ascii=True))


class FrozenCoreTests(unittest.TestCase):
    frozen: dict[str, bytes]
    rebuilt: dict[str, bytes]
    repeated: dict[str, bytes]
    objects: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = {p.name: p.read_bytes()
                      for p in (FROZEN / "fixtures").glob("*.json")}
        cls.rebuilt = cls.rebuild()
        cls.repeated = cls.rebuild()
        cls.objects = {name: json.loads(body) for name, body in cls.rebuilt.items()}

    @staticmethod
    def rebuild() -> dict[str, bytes]:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()),
             "--build-in-memory"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(f"Frozen rebuild failed:\n{result.stdout}\n{result.stderr}")
        return {name: text.encode("utf-8")
                for name, text in json.loads(result.stdout).items()}

    def test_frozen_fixture_bytes(self) -> None:
        self.assertEqual(set(self.frozen), FIXTURE_NAMES)
        self.assertEqual(set(self.rebuilt), FIXTURE_NAMES)
        for name in sorted(FIXTURE_NAMES):
            with self.subTest(fixture=name):
                self.assertEqual(self.rebuilt[name], self.frozen[name])

    def test_independent_rebuilds_are_identical(self) -> None:
        self.assertEqual(self.rebuilt, self.repeated)

    def test_frozen_schema_and_runtime_model(self) -> None:
        schema = json.loads((FROZEN / "canonical_model_v1.schema.json")
                            .read_text(encoding="utf-8"))
        for name, fixture in self.objects.items():
            with self.subTest(fixture=name):
                jsonschema.validate(fixture, schema)
                model = CanonicalFiling.model_validate(fixture)
                self.assertEqual(model.filing_id, fixture["filing_id"])
                self.assertEqual(
                    model.model_dump(mode="json", exclude_unset=True), fixture)

    def test_fallback_and_divergent_payload_are_preserved(self) -> None:
        ibe = self.objects["ibe_fy2024.json"]
        self.assertEqual(len(ibe["submission_variants"]), 1)
        self.assertTrue(any(v["resolution_mode"] == "FALLBACK_TO_ES"
                            for v in ibe["view_resolutions"]))
        bbva = self.objects["bbva_fy2024.json"]
        self.assertEqual(bbva["fact_examples"][0]["en"]["value"], "-98000000")

    def test_variant_scoped_lifecycle_is_preserved(self) -> None:
        tef = self.objects["tef_20484.json"]
        en = next(v for v in tef["submission_variants"]
                  if v["submission_language"] == "en")
        es = next(v for v in tef["submission_variants"]
                  if v["submission_language"] == "es")
        self.assertEqual(len(en["variant_versions"]), 2)
        self.assertEqual(len(es["variant_versions"]), 1)
        self.assertIs(en["variant_versions"][0]["observed"], False)
        march = next(e for e in tef["version_events"]
                     if e["event_id"].endswith("2025-03-13"))
        february = next(e for e in tef["version_events"]
                        if e["event_id"].endswith("2025-02-28"))
        self.assertIsNone(march["source_nreg"])
        self.assertEqual(march["affects"][0]["variant_id"], en["variant_id"])
        self.assertEqual(february["scope_status"], "VARIANT_SCOPE_NOT_OBSERVABLE")


class CoreUnitTests(unittest.TestCase):
    def test_installed_version_matches_library(self) -> None:
        self.assertEqual(importlib.metadata.version("opencnmv"), opencnmv.__version__)
        self.assertEqual(opencnmv.MODEL_CONTRACT, "CANONICAL_MODEL_V1")

    def test_serialization_uses_utf8_and_lf(self) -> None:
        self.assertEqual(canonical_bytes({"name": "España"}),
                         b'{\n "name": "Espa\xc3\xb1a"\n}')

    def test_observed_variant_requires_artifact_set(self) -> None:
        with self.assertRaises(ValidationError):
            VariantVersion(variant_version_id="filing#es#v1", variant_id="filing#es",
                           observed=True)
        unobserved = VariantVersion(variant_version_id="filing#es#v1",
                                    variant_id="filing#es", observed=False)
        self.assertIsNone(unobserved.artifact_set_id)

    def test_fact_identity_preserves_semantic_dimensions(self) -> None:
        key = fact_key("ifrs:Assets", "issuer", "2024-12-31",
                       {"axis:B": "member:B", "axis:A": "member:A"}, "iso4217:EUR", "es")
        base = fact_id(key, "filing#es#v1")
        reordered = dict(key, dimensions={"axis:A": "member:A", "axis:B": "member:B"})
        self.assertEqual(base, fact_id(reordered, "filing#es#v1"))
        for field, value in (
            ("concept", "ifrs:Liabilities"), ("entity", "other-issuer"),
            ("period", "2023-12-31"), ("dimensions", {}),
            ("unit", "iso4217:USD"), ("language", "en"),
        ):
            with self.subTest(field=field):
                self.assertNotEqual(base, fact_id(dict(key, **{field: value}), "filing#es#v1"))
        self.assertNotEqual(base, fact_id(key, "filing#es#v2"))


if __name__ == "__main__":
    if sys.argv[1:] == ["--build-in-memory"]:
        build_in_memory()
    else:
        unittest.main()
