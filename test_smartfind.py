"""Run with:  python -m unittest -v      (no Streamlit needed)"""
import unittest
import importlib.util
from contextlib import nullcontext
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import smartfind_mail
import smartfind_vision
import smartfind_store
import smartfind_theme
from smartfind_auth import create_guest_credentials, guest_code_digest, resolve_role
from smartfind_core import (NOTIFY_THRESHOLD, calculate_match_score, compare_locations,
                            find_pairs, new_notifications, normalize_location)


def report(rid, rtype, **kw):
    base = {"id": rid, "type": rtype, "item": "Black Smartphone", "category": "Smartphone",
            "color": "Black", "location": "Laboratory", "date": "2026-10-08",
            "description": "cracked screen with black case", "photo": None,
            "status": "Searching" if rtype == "Lost" else "Reported", "user_email": "a@tip.edu.ph"}
    base.update(kw)
    return base


def state(rows, rule):
    return next(r for r in rows if r["rule"] == rule)


class LocationTests(unittest.TestCase):
    def test_identical_locations_match_fully(self):
        pts, _, _, st_ = compare_locations("Laboratory", "laboratory ")
        self.assertEqual((pts, st_), (20, "match"))

    def test_room_code_formats_are_equal(self):
        for other in ("Q5312", "q 5312", "Room Q-5312"):
            self.assertEqual(compare_locations("Q-5312", other)[0], 20, other)

    def test_same_first_two_letters_but_unrelated_earns_nothing(self):
        # old rule: both start with "st" -> partial points
        self.assertEqual(compare_locations("Student Lounge", "Study Hall")[0], 0)
        self.assertEqual(compare_locations("Canteen", "Cashier Window")[0], 0)

    def test_related_locations_earn_partial(self):
        self.assertEqual(compare_locations("Library — 2nd Floor", "Library")[0], 12)   # same area
        self.assertEqual(compare_locations("Computer Lab", "Laboratory")[0], 12)       # alias
        self.assertEqual(compare_locations("Q-5312", "Q-5301")[0], 12)                 # same building+floor
        self.assertEqual(compare_locations("Q-5312", "Q-4201")[0], 8)                  # same building
        self.assertEqual(compare_locations("Q-5312", "R-5312")[0], 0)                  # other building
        self.assertEqual(compare_locations("Q-5312", "Library")[0], 0)

    def test_room_code_matches_inside_longer_location_text(self):
        self.assertEqual(compare_locations("q-5312 po nakita", "Q-5312")[:1], (20,))

    def test_shared_location_keyword_matches_inside_longer_text(self):
        pts, detail, _, state_ = compare_locations("sa may auditorium", "near the auditorium entrance")
        self.assertEqual((pts, detail, state_), (12, "Same location keyword", "partial"))

    def test_close_location_keyword_matches_inside_longer_text(self):
        pts, detail, _, state_ = compare_locations("sa may congre", "congregrating area")
        self.assertEqual((pts, detail, state_), (8, "Close location keyword", "partial"))

    def test_unrelated_keywords_do_not_match(self):
        self.assertEqual(compare_locations("sa may congre", "near cafeteria")[0], 0)

    def test_missing_location_earns_nothing(self):
        for a, b in (("", ""), ("Laboratory", ""), ("  ", "Laboratory")):
            pts, _, _, st_ = compare_locations(a, b)
            self.assertEqual((pts, st_), (0, "unverified"))

    def test_normalize_handles_none(self):
        self.assertEqual(normalize_location(None)["text"], "")


class ScoreTests(unittest.TestCase):
    def test_identical_reports_score_100(self):
        s, rows = calculate_match_score(report("L1", "Lost"), report("F1", "Found"))
        self.assertEqual(s, 100)
        self.assertEqual(len(rows), 5)
        self.assertEqual(sum(r["pts"] for r in rows), s)

    def test_score_never_exceeds_100(self):
        s, _ = calculate_match_score(report("L1", "Lost"), report("F1", "Found"))
        self.assertLessEqual(s, 100)

    def test_missing_optional_color_and_description_are_unverified(self):
        lost = report("L1", "Lost", color="", description="")
        s, rows = calculate_match_score(lost, report("F1", "Found"))
        self.assertEqual(state(rows, "Color")["state"], "unverified")
        self.assertEqual(state(rows, "Description")["state"], "unverified")
        self.assertEqual(s, 100 - 20 - 10)

    def test_two_blank_colors_do_not_count_as_a_match(self):
        s, rows = calculate_match_score(report("L1", "Lost", color=""), report("F1", "Found", color=""))
        self.assertEqual(state(rows, "Color")["pts"], 0)

    def test_different_categories_lose_category_points_and_cannot_be_strong(self):
        s, rows = calculate_match_score(report("L1", "Lost"), report("F1", "Found", category="Keys"))
        self.assertEqual(state(rows, "Category")["pts"], 0)
        self.assertLess(s, NOTIFY_THRESHOLD)

    def test_other_vs_other_is_only_partial(self):
        s, rows = calculate_match_score(report("L1", "Lost", category="Other"),
                                        report("F1", "Found", category="Other"))
        self.assertEqual(state(rows, "Category")["pts"], 10)

    def test_unrelated_same_prefix_location_lowers_score(self):
        s, rows = calculate_match_score(report("L1", "Lost", location="Student Lounge"),
                                        report("F1", "Found", location="Study Hall"))
        self.assertEqual(state(rows, "Location")["pts"], 0)
        self.assertEqual(s, 80)


class PairAndNotificationTests(unittest.TestCase):
    def test_resolved_reports_are_excluded_from_pairs(self):
        reps = [report("L1", "Lost"), report("F1", "Found")]
        self.assertEqual(len(find_pairs(reps)), 1)
        reps[0]["status"] = "Resolved"
        self.assertEqual(find_pairs(reps), [])
        reps[0]["status"], reps[1]["status"] = "Searching", "Resolved"
        self.assertEqual(find_pairs(reps), [])

    def test_resolved_reports_never_notify(self):
        reps = [report("L1", "Lost", status="Resolved"), report("F1", "Found")]
        self.assertEqual(new_notifications(reps, set(), "now"), [])

    def test_new_found_report_creates_one_notification(self):
        reps = [report("L1", "Lost")]
        self.assertEqual(new_notifications(reps, set(), "now"), [])      # nothing to match yet
        reps.append(report("F1", "Found"))                               # new report arrives
        made = new_notifications(reps, set(), "now")
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["pair_key"], "L1_F1")
        self.assertEqual(made[0]["recipient"], "a@tip.edu.ph")

    def test_both_report_owners_receive_match_notifications(self):
        lost = report("L1", "Lost", user_email="owner1@example.com")
        found = report("F1", "Found", user_email="owner2@example.com")
        made = new_notifications([lost, found], set(), "now")
        self.assertEqual({entry["recipient"] for entry in made},
                         {"owner1@example.com", "owner2@example.com"})
        self.assertEqual({entry["pair_key"] for entry in made}, {"L1_F1"})

    def test_recipient_identity_is_case_normalized(self):
        lost = report("L1", "Lost", user_email="Owner@Example.com")
        found = report("F1", "Found", user_email="owner@example.com")
        made = new_notifications([lost, found], set(), "now")
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["recipient"], "owner@example.com")

    def test_duplicate_notifications_are_prevented(self):
        reps = [report("L1", "Lost"), report("F1", "Found")]
        keys = set()
        first = new_notifications(reps, keys, "now")
        keys |= {n["key"] for n in first}
        self.assertEqual(len(first), 1)
        self.assertEqual(new_notifications(reps, keys, "later"), [])     # rerun: no duplicate

    def test_weak_match_is_listed_but_does_not_notify(self):
        reps = [report("L1", "Lost"), report("F1", "Found", category="Keys", color="Silver",
                                              location="Canteen", date="2026-10-20")]
        self.assertEqual(new_notifications(reps, set(), "now"), [])

    def test_each_pair_notifies_separately(self):
        reps = [report("L1", "Lost"), report("F1", "Found"), report("F2", "Found")]
        self.assertEqual(sorted(n["pair_key"] for n in new_notifications(reps, set(), "now")), ["L1_F1", "L1_F2"])


class MatchingRefinementTests(unittest.TestCase):
    def test_color_partial_needs_a_shared_word_not_a_substring(self):
        _, rows = calculate_match_score(report("L1", "Lost", color="Navy Blue"), report("F1", "Found", color="Blue"))
        self.assertEqual(state(rows, "Color")["pts"], 10)
        _, rows = calculate_match_score(report("L1", "Lost", color="Tan"), report("F1", "Found", color="Titanium"))
        self.assertEqual(state(rows, "Color")["pts"], 0)

    def test_description_ignores_punctuation(self):
        lost = report("L1", "Lost", description="Black cover. Cracked, screen!")
        found = report("F1", "Found", description="black cover cracked screen")
        _, rows = calculate_match_score(lost, found)
        self.assertEqual(state(rows, "Description")["pts"], 10)

    def test_brand_is_supporting_evidence_without_inflating_score(self):
        lost = report("L1", "Lost", brand="ASUS")
        found = report("F1", "Found", brand="asus")
        score, rows = calculate_match_score(lost, found)
        self.assertEqual(state(rows, "Brand")["pts"], 5)
        self.assertEqual(state(rows, "Description")["pts"], 5)
        self.assertEqual(score, 100)

    def test_brand_mismatch_reduces_score_and_missing_brand_is_unverified(self):
        score, rows = calculate_match_score(report("L1", "Lost", brand="ASUS"),
                                            report("F1", "Found", brand="Acer"))
        self.assertEqual(state(rows, "Brand")["state"], "differ")
        self.assertEqual(score, 95)
        _, rows = calculate_match_score(report("L1", "Lost", brand="ASUS"), report("F1", "Found"))
        self.assertEqual(state(rows, "Brand")["state"], "unverified")


class VisionScopeTests(unittest.TestCase):
    """Real model metadata and image-analysis helpers are used; OCR stays optional."""

    @unittest.skipUnless(importlib.util.find_spec("ultralytics"), "ultralytics is not installed")
    def test_trained_model_and_embedded_categories_are_available(self):
        self.assertTrue(smartfind_vision.MODEL_PATH.is_file())
        self.assertEqual(smartfind_vision.RECOGNIZER_MODE, "model")
        self.assertTrue(smartfind_vision.get_model_categories())

    def test_both_model_versions_have_checkpoints_and_labels(self):
        self.assertEqual(set(smartfind_vision.MODEL_PATHS), {"v1", "v2"})
        self.assertEqual(set(smartfind_vision.MODEL_LABELS), {"v1", "v2"})
        self.assertEqual(smartfind_vision.MODEL_LABELS, {"v1": "V1", "v2": "V2"})
        self.assertTrue(smartfind_vision.MODEL_PATHS["v1"].is_file())
        self.assertTrue(smartfind_vision.MODEL_PATHS["v2"].is_file())
        self.assertEqual(len(smartfind_vision.TRAINED_CATEGORIES), 24)

    def test_model_loader_uses_the_selected_checkpoint(self):
        created = []

        class FakeYOLO:
            def __init__(self, path):
                self.path = path
                created.append(path)

        def load_yolov5(path, device):
            model = FakeYOLO(path)
            model.device = device
            return model

        allowed_classes = []

        def safe_globals(classes):
            allowed_classes.extend(classes)
            return nullcontext()

        common_classes = {
            name: type(name, (), {})
            for name in ("Bottleneck", "C3", "Concat", "Conv", "SPPF")
        }
        yolo_classes = {
            name: type(name, (), {}) for name in ("Detect", "DetectionModel")
        }
        nn_classes = {
            name: type(name, (), {})
            for name in ("BatchNorm2d", "Conv2d", "ModuleList", "Sequential",
                         "SiLU", "MaxPool2d", "Upsample")
        }
        models_package = types.ModuleType("models")
        models_package.__path__ = []
        yolov5_package = types.ModuleType("yolov5")
        yolov5_package.__path__ = []
        yolov5_models_package = types.ModuleType("yolov5.models")
        yolov5_models_package.__path__ = []
        common_module = types.ModuleType("models.common")
        common_module.__dict__.update(common_classes)
        packaged_common_module = types.ModuleType("yolov5.models.common")
        packaged_common_module.__dict__.update(common_classes)
        yolo_module = types.ModuleType("models.yolo")
        yolo_module.__dict__.update(yolo_classes)
        packaged_yolo_module = types.ModuleType("yolov5.models.yolo")
        packaged_yolo_module.__dict__.update(yolo_classes)
        torch_module = types.ModuleType("torch")
        torch_module.serialization = types.SimpleNamespace(safe_globals=safe_globals)
        nn_module = types.ModuleType("torch.nn")
        nn_module.__dict__.update(nn_classes)
        torch_module.nn = nn_module
        models_package.common = common_module
        models_package.yolo = yolo_module
        yolov5_models_package.common = packaged_common_module
        yolov5_models_package.yolo = packaged_yolo_module
        yolov5_package.models = yolov5_models_package
        yolov5_package.load = load_yolov5

        smartfind_vision._load_model.cache_clear()
        try:
            with patch.dict(sys.modules, {
                "ultralytics": types.SimpleNamespace(YOLO=FakeYOLO),
                "yolov5": yolov5_package,
                "yolov5.models": yolov5_models_package,
                "yolov5.models.common": packaged_common_module,
                "yolov5.models.yolo": packaged_yolo_module,
                "torch": torch_module,
                "torch.nn": nn_module,
                "models": models_package,
                "models.common": common_module,
                "models.yolo": yolo_module,
            }):
                first = smartfind_vision._load_model("v1")
                second = smartfind_vision._load_model("v2")
            self.assertEqual(first.path, str(smartfind_vision.MODEL_PATHS["v1"]))
            self.assertEqual(second.path, str(smartfind_vision.MODEL_PATHS["v2"]))
            self.assertEqual(second.device, "cpu")
            self.assertEqual(second.conf, smartfind_vision.CONFIDENCE_THRESHOLD)
            self.assertEqual(len(created), 2)
            self.assertIn((yolo_classes["DetectionModel"], "models.yolo.DetectionModel"), allowed_classes)
            self.assertIn((common_classes["C3"], "models.common.C3"), allowed_classes)
            self.assertIn(
                (smartfind_vision.PosixPath, "pathlib._local.PosixPath"), allowed_classes)
        finally:
            smartfind_vision._load_model.cache_clear()

    def test_v1_detector_normalizes_its_label_and_uses_selected_model(self):
        from PIL import Image
        from io import BytesIO

        class Value:
            def __init__(self, value):
                self.value = value

            def item(self):
                return self.value

            def tolist(self):
                return self.value

            def argmax(self):
                return Value(0)

        class Box:
            cls = Value(0)
            conf = Value(0.91)
            xyxy = [Value([2, 2, 28, 28])]

        class Boxes:
            conf = Value(0)

            def __len__(self):
                return 1

            def __getitem__(self, index):
                self.asserted_index = index
                return Box()

        model = types.SimpleNamespace(
            names={0: "Smartphone"},
            predict=lambda **_kwargs: [types.SimpleNamespace(boxes=Boxes())],
        )
        image = Image.new("RGB", (32, 32), "blue")
        stream = BytesIO()
        image.save(stream, format="PNG")
        with patch.object(smartfind_vision, "_load_model", return_value=model) as load_model, \
                patch.object(smartfind_vision, "read_text_candidates", return_value=([], [])):
            result = smartfind_vision.classify_image(stream.getvalue(), model_version="v1")
        load_model.assert_called_once_with("v1")
        self.assertEqual(result["category"], "Mobile phone")
        self.assertEqual(result["source"], "model")

    def test_v2_detector_reads_yolov5_predictions_and_normalizes_label(self):
        from PIL import Image
        from io import BytesIO

        class Tensor:
            def __init__(self, value):
                self.value = value

            def item(self):
                return self.value

            def tolist(self):
                return self.value

            def argmax(self):
                return Tensor(0)

        class Detection:
            def __getitem__(self, key):
                values = [2, 2, 28, 28, 0.91, 0]
                return Tensor(values[key])

        class Detections:
            def __len__(self):
                return 1

            def __getitem__(self, key):
                return Tensor(0) if isinstance(key, tuple) else Detection()

        class Predictions:
            pred = [Detections()]

        class FakeYoloV5Model:
            names = {0: "Smartphone"}

            def __call__(self, *_args, **_kwargs):
                return Predictions()

        model = FakeYoloV5Model()
        image = Image.new("RGB", (32, 32), "blue")
        stream = BytesIO()
        image.save(stream, format="PNG")
        with patch.object(smartfind_vision, "_load_model", return_value=model) as load_model, \
                patch.object(smartfind_vision, "read_text_candidates", return_value=([], [])):
            result = smartfind_vision.classify_image(stream.getvalue(), model_version="v2")
        load_model.assert_called_once_with("v2")
        self.assertEqual(result["category"], "Mobile phone")
        self.assertEqual(result["confidence"], 91)

    def test_category_labels_are_normalized_across_models_and_manual_input(self):
        aliases = {
            "Smartphone": "Mobile phone",
            "mobile-phone": "Mobile phone",
            "ID Card": "StudentID_card",
            "studentid card": "StudentID_card",
            "Eyeglasses": "Glasses",
            "Water Bottle": "Water bottle",
            "powerbank": "Power bank",
            "iPad Air": "iPad-Air",
        }
        for source, canonical in aliases.items():
            with self.subTest(source=source):
                self.assertEqual(smartfind_vision.normalize_category(source), canonical)

    def test_detected_brand_is_first_and_normalized_for_auto_selection(self):
        candidates = smartfind_vision.normalize_brand_candidates(
            ["Samsung", "Apple"], "Samsung Electronics Co., Ltd.")
        self.assertEqual(candidates, ["Samsung", "Apple"])

    def test_color_estimator_returns_named_color(self):
        from PIL import Image
        self.assertEqual(smartfind_vision.estimate_dominant_color(Image.new("RGB", (30, 30), "red")), "Red")

    def test_invalid_image_fails_as_a_user_correctable_error(self):
        with self.assertRaisesRegex(ValueError, "readable image"):
            smartfind_vision.classify_image(b"not-an-image")

    def test_empty_photo_returns_empty_detection_shape(self):
        result = smartfind_vision.classify_image(b"")
        self.assertIsNone(result["category"])
        self.assertIsNone(result["bbox"])

    def test_ocr_groups_words_and_ranks_common_brand_correction(self):
        data = {
            "text": ["Sam", "sunq", "case"],
            "conf": ["91", "85", "98"],
            "block_num": [1, 1, 1], "par_num": [1, 1, 1], "line_num": [1, 1, 2],
        }
        candidates = smartfind_vision._ocr_candidate_lines(data)
        brands, raw_text = smartfind_vision._rank_candidates(candidates, "Mobile phone")
        self.assertEqual(brands[0], "Samsung")
        self.assertIn("Sam sunq", raw_text)

    def test_ocr_wrapper_returns_brand_and_raw_text_candidates(self):
        from unittest.mock import patch
        from PIL import Image
        with patch.object(smartfind_vision, "_rapidocr_candidates", return_value=[("SAMSUNG", 94)]):
            brands, raw_text = smartfind_vision.read_text_candidates(
                Image.new("RGB", (240, 120), "white"), "Mobile phone")
        self.assertIn("Samsung", brands)
        self.assertIn("SAMSUNG", raw_text)

    def test_brand_vocabulary_matches_all_trained_categories(self):
        self.assertEqual(len(smartfind_vision.BRANDS_BY_CATEGORY), 22)
        self.assertIn("Samsung", smartfind_vision.BRANDS_BY_CATEGORY["Mobile phone"])
        brands, _ = smartfind_vision._rank_candidates([("SAMSUNG", 94)], "Mobile phone")
        self.assertEqual(brands, ["Samsung"])

    def test_brand_legal_names_and_manual_category_aliases_normalize(self):
        self.assertEqual(smartfind_vision.normalize_brand("Samsung Electronics Co., Ltd."), "Samsung")
        self.assertEqual(smartfind_vision.normalize_brand("Apple Inc."), "Apple")
        self.assertEqual(smartfind_vision.normalize_brand("  Acme Labs  "), "Acme Labs")
        self.assertIn("Samsung", smartfind_vision.brands_for_category("Smartphone"))
        self.assertIn("Casio", smartfind_vision.brands_for_category("Calculator"))

    def test_full_photo_fallback_keeps_color_and_ocr_when_category_missing(self):
        from unittest.mock import patch
        from PIL import Image
        image = Image.new("RGB", (100, 100), "black")
        with patch.object(smartfind_vision, "estimate_dominant_color", return_value="Black"), \
                patch.object(smartfind_vision, "read_text_candidates",
                             return_value=(["Samsung"], ["SAMSUNG"])):
            result = smartfind_vision._fallback_image_analysis(image, "No supported object detected")
        self.assertIsNone(result["category"])
        self.assertEqual(result["color"], "Black")
        self.assertEqual(result["brand_candidates"], ["Samsung"])
        self.assertEqual(result["source"], "image-fallback")

    def test_ocr_preprocessing_upscales_small_item_crops(self):
        from PIL import Image
        enhanced, thresholded = smartfind_vision._prepare_ocr_images(Image.new("RGB", (100, 50), "white"))
        self.assertGreater(enhanced.width, 100)
        self.assertEqual(enhanced.size, thresholded.size)


class ReportStoreTests(unittest.TestCase):
    def test_postgres_schema_is_initialized_once_and_queries_contain_no_ddl(self):
        class FakeCursor:
            rowcount = 1

            def fetchall(self):
                return []

            def fetchone(self):
                return None

        class FakeConnection:
            def __init__(self):
                self.statements = []
                self.commits = 0
                self.closed = False

            def execute(self, statement, params=None):
                self.statements.append(statement)
                return FakeCursor()

            def commit(self):
                self.commits += 1

            def rollback(self):
                pass

            def close(self):
                self.closed = True

        connections = []

        def connect(*_args, **_kwargs):
            connection = FakeConnection()
            connections.append(connection)
            return connection

        old_url = smartfind_store._SUPABASE_DATABASE_URL
        old_initialized = set(smartfind_store._INITIALIZED_TARGETS)
        fake_psycopg = types.SimpleNamespace(connect=connect)
        try:
            smartfind_store._INITIALIZED_TARGETS.clear()
            smartfind_store.configure_supabase("postgresql://example.test/smartfind")
            with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
                smartfind_store.initialize_storage()
                self.assertEqual(len(connections), 1)
                ddl = connections[0].statements
                self.assertTrue(any("CREATE TABLE" in statement for statement in ddl))
                self.assertTrue(any("CREATE TABLE IF NOT EXISTS guest_accounts" in statement
                                    for statement in ddl))
                self.assertTrue(any("CREATE TABLE IF NOT EXISTS user_preferences" in statement
                                    for statement in ddl))
                self.assertTrue(any("CREATE TABLE IF NOT EXISTS report_drafts" in statement
                                    for statement in ddl))
                self.assertTrue(any("ENABLE ROW LEVEL SECURITY" in statement for statement in ddl))
                with smartfind_store._connect() as connection:
                    connection.execute("SELECT payload::text FROM reports")
                self.assertEqual(len(connections), 2)
                self.assertEqual(connections[1].statements, ["SELECT payload::text FROM reports"])
        finally:
            smartfind_store.configure_supabase(old_url)
            smartfind_store._INITIALIZED_TARGETS.clear()
            smartfind_store._INITIALIZED_TARGETS.update(old_initialized)

    def test_guest_accounts_store_and_lookup_only_recovery_code_digests(self):
        guest_id = "guest-identity"
        code_hash = "a" * 64

        class FakeCursor:
            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class FakeConnection:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=None):
                self.statements.append((statement, params))
                return FakeCursor((guest_id,))

        connection = FakeConnection()
        with patch.object(smartfind_store, "_connect", return_value=nullcontext(connection)):
            smartfind_store.create_guest_account(guest_id, code_hash)
            self.assertEqual(smartfind_store.find_guest_account(code_hash), guest_id)

        self.assertIn("INSERT INTO guest_accounts", connection.statements[0][0])
        self.assertEqual(connection.statements[0][1], (guest_id, code_hash))
        self.assertIn("WHERE recovery_code_hash = %s", connection.statements[1][0])
        self.assertEqual(connection.statements[1][1], (code_hash,))

    def test_ui_preferences_and_drafts_are_scoped_to_normalized_owner(self):
        class FakeCursor:
            rowcount = 1

            def __init__(self, row=None):
                self.row = row

            def fetchone(self):
                return self.row

        class FakeConnection:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=None):
                self.statements.append((statement, params))
                if "FROM user_preferences" in statement:
                    return FakeCursor(({"theme": "dark"},))
                if "FROM report_drafts" in statement:
                    return FakeCursor(({"location": "Library"},))
                return FakeCursor()

        connection = FakeConnection()
        with patch.object(smartfind_store, "_connect", return_value=nullcontext(connection)):
            self.assertEqual(smartfind_store.load_user_preferences("User@Example.com"),
                             {"theme": "dark"})
            smartfind_store.save_user_preferences("User@Example.com", {"theme": "dark"})
            self.assertEqual(smartfind_store.load_report_draft("User@Example.com", "Lost"),
                             {"location": "Library"})
            smartfind_store.save_report_draft("User@Example.com", "Lost", {"location": "Library"})
            smartfind_store.delete_report_draft("User@Example.com", "Lost")

        self.assertEqual(connection.statements[0][1], ("user@example.com",))
        self.assertEqual(connection.statements[1][1][0], "user@example.com")
        self.assertEqual(connection.statements[2][1], ("user@example.com", "Lost"))
        self.assertEqual(connection.statements[3][1][:2], ("user@example.com", "Lost"))
        self.assertEqual(connection.statements[4][1], ("user@example.com", "Lost"))

    def test_guest_notifications_are_in_app_only(self):
        class FakeCursor:
            rowcount = 1

            def fetchall(self):
                return []

        class FakeConnection:
            def __init__(self):
                self.statements = []

            def execute(self, statement, params=None):
                self.statements.append((statement, params))
                return FakeCursor()

        connection = FakeConnection()
        with patch.object(smartfind_store, "_connect", return_value=nullcontext(connection)):
            smartfind_store.save_notifications([
                {"key": "guest-key", "pair_key": "L1_F1", "recipient": "guest:123",
                 "item": "Black Smartphone", "score": 100, "time": "now"},
                {"key": "student-key", "pair_key": "L2_F2", "recipient": "student@example.com",
                 "item": "Blue Keys", "score": 90, "time": "now"},
            ])
            smartfind_store.pending_notification_emails()

        self.assertEqual(connection.statements[0][1][-1], "not_applicable")
        self.assertEqual(connection.statements[1][1][-1], "pending")
        self.assertIn("recipient NOT LIKE 'guest:%'", connection.statements[2][0])


class AuthenticationTests(unittest.TestCase):
    def test_only_verified_allowlisted_identities_receive_roles(self):
        self.assertEqual(resolve_role("Student@TIP.edu.ph", True, ["tip.edu.ph"], []), "student")
        self.assertEqual(resolve_role("admin@example.com", True, [], ["ADMIN@example.com"]), "admin")
        self.assertIsNone(resolve_role("user@other.edu", True, ["tip.edu.ph"], []))
        self.assertIsNone(resolve_role("user@tip.edu.ph", False, ["tip.edu.ph"], []))

    def test_guest_recovery_code_is_high_entropy_and_only_a_digest_is_returned(self):
        guest_id, recovery_code, code_hash = create_guest_credentials()

        self.assertEqual(len(guest_id), 32)
        self.assertEqual(guest_code_digest(recovery_code), code_hash)
        self.assertNotEqual(recovery_code, code_hash)
        self.assertIsNone(guest_code_digest("not-a-valid-code"))


class ThemeTests(unittest.TestCase):
    def test_all_declared_theme_foreground_background_pairs_meet_wcag_aa(self):
        for theme, tokens in smartfind_theme.THEME_TOKENS.items():
            for foreground, background in smartfind_theme.CONTRAST_PAIRS:
                with self.subTest(theme=theme, foreground=foreground, background=background):
                    self.assertGreaterEqual(
                        smartfind_theme.contrast_ratio(tokens[foreground], tokens[background]), 4.5)

    def test_theme_stylesheet_styles_auth_controls_and_nested_button_labels(self):
        for theme in smartfind_theme.THEME_TOKENS:
            stylesheet = smartfind_theme.theme_stylesheet(theme)
            with self.subTest(theme=theme):
                self.assertIn("--sf-primary-bg:", stylesheet)
                self.assertIn("--sf-primary-text:", stylesheet)
                self.assertIn('button[data-testid^="stBaseButton-primary"] *', stylesheet)
                self.assertIn('button[kind="primary"] *', stylesheet)
                self.assertIn(':not([kind="primary"]) *', stylesheet)
                self.assertIn('[data-testid="stTextInputRootElement"] button svg', stylesheet)

    def test_theme_stylesheet_covers_dark_surfaces_and_selected_sidebar_text(self):
        stylesheet = smartfind_theme.theme_stylesheet("dark", active_nav_index=0)
        self.assertIn("background:var(--sf-surface) !important", stylesheet)
        self.assertIn('.stApp section[data-testid="stSidebar"] .st-key-nav_0', stylesheet)
        self.assertIn('button[data-testid="stBaseButton-secondary"] *', stylesheet)
        self.assertIn("color:var(--sf-sidebar-active-text) !important", stylesheet)
        self.assertIn("color:var(--sf-alert-text) !important", stylesheet)

    def test_theme_stylesheet_overrides_streamlit_native_photo_controls(self):
        for theme in smartfind_theme.THEME_TOKENS:
            stylesheet = smartfind_theme.theme_stylesheet(theme)
            with self.subTest(theme=theme):
                self.assertIn('[data-testid="stFileUploaderDropzone"]', stylesheet)
                self.assertIn('[data-testid="stFileUploaderDropzoneInstructions"]', stylesheet)
                self.assertIn('[data-testid="stRadioOption"][data-selected="true"]', stylesheet)
                self.assertIn('[data-testid="stProgressBarTrack"] > div', stylesheet)
                self.assertIn('[data-testid="stExpander"] summary:hover', stylesheet)

    def test_theme_stylesheet_defaults_unknown_theme_to_light(self):
        self.assertIn("color-scheme:light", smartfind_theme.theme_stylesheet("unknown"))

    def test_theme_stylesheet_is_injected_before_auth_and_after_app_styles(self):
        source = Path("main.py").read_text(encoding="utf-8")
        style_calls = [index for index in range(len(source))
                       if source.startswith("st.markdown(theme_stylesheet(", index)]
        self.assertEqual(len(style_calls), 2)
        self.assertLess(style_calls[0], source.index("def _current_user"))
        self.assertGreater(style_calls[1], source.index("active_idx ="))
        self.assertNotIn("light_css", source)
        self.assertNotIn("theme_css =", source)


class MobileNavigationTests(unittest.TestCase):
    def test_mobile_menu_is_visible_and_uses_the_same_navigation_targets(self):
        source = Path("main.py").read_text(encoding="utf-8")
        mobile_css = source[source.index("@media (max-width: 700px)"):]
        self.assertIn('key="mobile_nav"', source)
        self.assertIn('st.popover("☰ Menu")', source)
        self.assertIn('navigate(name)', source)
        self.assertIn(".st-key-mobile_nav", mobile_css)
        self.assertIn("min-width:44px", mobile_css)

    def test_each_session_selects_and_passes_its_own_detector(self):
        source = Path("main.py").read_text(encoding="utf-8")
        step_one = source[source.index('if step == 1:'):
                           source.index('elif step == 2:')]
        self.assertIn('key="vision_model"', step_one)
        self.assertIn("analyze_photo(photo_bytes, st.session_state.vision_model)", source)
        self.assertIn("This choice only changes photo analysis in your session.", source)
        self.assertNotIn('key="vision_model"', source[source.index("with st.sidebar:"):source.index('html(f"""', source.index("with st.sidebar:"))])

    def test_detected_brand_is_preselected_in_report_form(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("normalize_brand_candidates(", source)
        self.assertIn('brand_candidates + brands_for_category(cat)', source)
        self.assertIn('brand_candidates if value in brand_options', source)

    def test_wizard_requires_a_review_before_publishing_and_persists_drafts(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('st.progress(step / 3', source)
        self.assertIn('"Save draft and review"', source)
        self.assertIn('"Submit report"', source)
        self.assertIn("persist_report_draft(report_type", source)
        self.assertIn("remove_report_draft(report_type)", source)

    def test_theme_motion_and_responsive_styles_are_explicit(self):
        source = Path("main.py").read_text(encoding="utf-8")
        theme_styles = smartfind_theme.theme_stylesheet("dark")
        self.assertIn('st.toggle("Dark theme"', source)
        self.assertIn("@media (prefers-reduced-motion: reduce)", theme_styles)
        self.assertIn("@media (max-width: 900px)", source)
        self.assertIn("@media (max-width: 700px)", source)
        self.assertIn(":focus-visible", theme_styles)


class EmailDeliveryTests(unittest.TestCase):
    def test_mail_requires_smtp_credentials(self):
        self.assertFalse(smartfind_mail.is_configured({}))
        self.assertTrue(smartfind_mail.is_configured({
            "smtp_host": "smtp.gmail.com", "smtp_username": "a@example.com",
            "smtp_password": "app-password"}))

    def test_email_uses_report_owner_and_match_details(self):
        server = MagicMock()
        notification = {"recipient": "owner@example.com", "item": "Black phone", "score": 86}
        settings = {"smtp_host": "smtp.gmail.com", "smtp_port": 587,
                    "smtp_username": "sender@gmail.com", "smtp_password": "app pass word",
                    "app_url": "https://smartfind.streamlit.app"}
        with patch("smartfind_mail.smtplib.SMTP", return_value=server) as smtp:
            smartfind_mail.send_match_email(notification, settings)
        smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=20)
        server.login.assert_called_once_with("sender@gmail.com", "apppassword")
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "owner@example.com")
        self.assertIn("86/100", message.get_content())
        self.assertIn("https://smartfind.streamlit.app", message.get_content())

    def test_smtp_probe_reports_the_stage_that_failed(self):
        server = MagicMock()
        server.starttls.side_effect = ConnectionError("TLS blocked")
        settings = {"smtp_host": "smtp.gmail.com", "smtp_port": 587,
                    "smtp_username": "sender@gmail.com", "smtp_password": "app-password"}
        with patch("smartfind_mail.smtplib.SMTP", return_value=server):
            with self.assertRaisesRegex(smartfind_mail.SMTPDeliveryError, "STARTTLS: ConnectionError"):
                smartfind_mail.test_smtp_connection(settings)

if __name__ == "__main__":
    unittest.main()
