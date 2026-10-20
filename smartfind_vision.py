"""Image perception: YOLO object detection, optional OCR, and pixel-color suggestions.

YOLO supplies an item category and bounding box; it does not identify an individual
item or prove ownership. OCR extracts candidate text only (it cannot recognize logos).
"""
from functools import lru_cache
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
import io
import os
import re
import pathlib
import os

MODEL_PATH = Path(os.environ.get("SMARTFIND_MODEL_PATH", Path(__file__).parent / "models" / "best (1).pt"))
CONFIDENCE_THRESHOLD = float(os.environ.get("SMARTFIND_DETECTION_CONFIDENCE", "0.15"))
RECOGNIZER_MODE = "model" if MODEL_PATH.is_file() else "unavailable"
AI_CATEGORIES = {}

_COLOR_PROTOTYPES = {
    "Black": (25, 25, 25), "White": (235, 235, 235), "Gray": (128, 128, 128),
    "Silver": (190, 195, 200), "Red": (210, 35, 45), "Orange": (235, 130, 35),
    "Yellow": (235, 215, 45), "Green": (45, 145, 65), "Blue": (40, 85, 200),
    "Purple": (125, 65, 160), "Pink": (225, 125, 165), "Brown": (125, 80, 45),
}

# Small, curated OCR vocabulary for visible wordmarks. These are examples of common
# brands for the 22 trained classes, not a promise that every product in the class
# uses one of these brands. Logo-only marks are outside OCR's capabilities.
BRANDS_BY_CATEGORY = {
    "Apple-Pencil": ["Apple", "Logitech", "Adonit", "Wacom", "ESR"],
    "Bag": ["JanSport", "Herschel", "Nike", "Adidas", "Fjallraven"],
    "Calculator": ["Casio", "Canon", "Texas Instruments", "Sharp", "Citizen"],
    "Charging-cable": ["Anker", "Apple", "Samsung", "UGREEN", "Baseus"],
    "Earphones": ["Apple", "Sony", "JBL", "Samsung", "Xiaomi"],
    "Glasses": ["Ray-Ban", "Oakley", "Gucci", "Sunnies Studios", "Gentle Monster"],
    "Keyboard": ["Logitech", "Razer", "Corsair", "Keychron", "Redragon"],
    "Keys": ["Yale", "Schlage", "Kwikset", "Master Lock", "ABUS"],
    "Laptop": ["Apple", "Dell", "HP", "Lenovo", "ASUS"],
    "Lecture-notes": ["Moleskine", "MUJI", "Kokuyo", "Campus", "Stabilo"],
    "Markers": ["Sharpie", "EXPO", "Crayola", "Pilot", "Zebra"],
    "Mobile phone": ["Samsung", "Apple", "Xiaomi", "Huawei", "OPPO"],
    "Mouse": ["Logitech", "Razer", "Corsair", "Microsoft", "HP"],
    "PC": ["HP", "Dell", "Lenovo", "ASUS", "Acer"],
    "Pen": ["Pilot", "Parker", "Uni-ball", "Zebra", "BIC"],
    "Screen": ["Samsung", "LG", "Dell", "ASUS", "Acer"],
    # ID cards and plain keys often have no readable consumer brand.
    "StudentID_card": [],
    "Wallet": ["Coach", "Fossil", "Herschel", "Secrid", "Louis Vuitton"],
    "Watch": ["Apple", "Casio", "Seiko", "Rolex", "Garmin"],
    "Water bottle": ["Hydro Flask", "Stanley", "Aquaflask", "Thermos", "Klean Kanteen"],
    "iPad-Air": ["Apple", "Logitech", "ESR", "ZAGG", "OtterBox"],
    "iPad-Pro": ["Apple", "Logitech", "ESR", "ZAGG", "OtterBox"],
}
ALL_KNOWN_BRANDS = list(dict.fromkeys(
    brand for brands in BRANDS_BY_CATEGORY.values() for brand in brands))

_BRAND_ALIASES = {
    "Apple": ("Apple Inc", "Apple Computer Inc", "Apple Computer"),
    "Samsung": ("Samsung Electronics", "Samsung Electronics Co Ltd",
                "Samsung Electronics Company Limited"),
    "HP": ("Hewlett Packard", "Hewlett-Packard", "Hewlett Packard Company",
           "HP Inc", "HP Incorporated"),
    "Canon": ("Canon Inc", "Canon Incorporated"),
    "Casio": ("Casio Computer", "Casio Computer Co Ltd",
              "Casio Computer Company Limited"),
    "Adidas": ("Adidas AG", "Adidas Group"),
    "Nike": ("Nike Inc", "Nike Incorporated"),
    "LG": ("LG Electronics", "LG Electronics Inc"),
    "Xiaomi": ("Xiaomi Inc", "Xiaomi Corporation", "Xiaomi Communications"),
    "Huawei": ("Huawei Technologies", "Huawei Technologies Co Ltd"),
    "ASUS": ("ASUSTeK", "ASUSTeK Computer", "ASUSTeK Computer Inc"),
}
_BRAND_LOOKUP = {
    re.sub(r"[^a-z0-9]", "", brand.casefold()): brand for brand in ALL_KNOWN_BRANDS
}
for _canonical_brand, _aliases in _BRAND_ALIASES.items():
    for _brand_alias in _aliases:
        _BRAND_LOOKUP[re.sub(r"[^a-z0-9]", "", _brand_alias.casefold())] = _canonical_brand


_CATEGORY_ALIASES = {
    "smartphone": "Mobile phone",
    "id card": "StudentID_card",
    "eyeglasses": "Glasses",
    "water bottle": "Water bottle",
}


def brands_for_category(category):
    """Return the curated list for a model category or its manual-form alias."""
    category = str(category or "").strip()
    category = _CATEGORY_ALIASES.get(category.casefold(), category)
    return list(BRANDS_BY_CATEGORY.get(category, []))


def normalize_brand(value):
    """Map known brand spellings and legal-name variants to the catalog label."""
    text = " ".join(str(value or "").strip().split())
    key = re.sub(r"[^a-z0-9]", "", text.casefold())
    return _BRAND_LOOKUP.get(key, text)




@lru_cache(maxsize=1)
def _load_model():
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"YOLO model was not found: {MODEL_PATH}"
        )

    import sys
    import os
    import pathlib
    import torch
    from unittest.mock import patch
    from yolov5 import YOLOv5

    # Compatibility for checkpoints saved with newer pathlib internals.
    sys.modules.setdefault("pathlib._local", pathlib)

    # Allow YOLOv5 to load our trusted, locally trained checkpoint.
    # This must be set before YOLOv5 calls torch.load().
    os.environ["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"

    if os.name == "nt":
        # Windows: handle Linux paths saved inside the checkpoint.
        with patch.object(pathlib, "PosixPath", pathlib.WindowsPath):
            model = YOLOv5(str(MODEL_PATH), device="cpu")
    else:
        # Linux (Streamlit Cloud): handle Windows paths saved inside the checkpoint.
        with patch.object(pathlib, "WindowsPath", pathlib.PosixPath):
            model = YOLOv5(str(MODEL_PATH), device="cpu")

    return model











def get_model_categories():
    """Return class names embedded in the trained model, or an empty list if unavailable."""
    try:
        names = _load_model().model.names
    except Exception:
        # Metadata should not prevent the app from starting if model loading fails;
        # image analysis reports the actionable error when a photo is submitted.
        return []
    if isinstance(names, dict):
        return [str(names[k]) for k in sorted(names)]
    return [str(name) for name in names]


def classify_image(image_bytes, filename="uploaded-image"):
    """Detect the most confident item and analyze its crop.

    Returns category, confidence (percent), color suggestion, OCR text candidate,
    bounding box, and source. Missing optional OCR support does not block detection.
    """
    if not image_bytes:
        return _empty_result("No image was provided")

    try:
        from PIL import Image, ImageOps
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
    except Exception as exc:
        raise ValueError("The uploaded file is not a readable image.") from exc

    model = _load_model()

    # Run YOLOv5 detection.
    results = model.predict(image, size=640)
    boxes = results.xyxy[0]

    if boxes is None or len(boxes) == 0:
        return _fallback_image_analysis(
            image,
            "No supported object detected; analyzed the full photo instead"
        )

    # Keep detections above the confidence threshold.
    boxes = boxes[boxes[:, 4] >= CONFIDENCE_THRESHOLD]

    if len(boxes) == 0:
        return _fallback_image_analysis(
            image,
            "No supported object detected; analyzed the full photo instead"
        )

    best_i = int(boxes[:, 4].argmax().item())
    box = boxes[best_i]

    class_id = int(box[5].item())
    names = model.model.names
    category = str(names[class_id])
    confidence = float(box[4].item()) * 100

    x1, y1, x2, y2 = [int(v) for v in box[:4].tolist()]
    x1, x2 = max(0, x1), min(image.width, x2)
    y1, y2 = max(0, y1), min(image.height, y2)
    crop = image.crop((x1, y1, x2, y2))
    if crop.width and crop.height:
        # Ignore a narrow amount of box-edge background when estimating the item color.
        inset = (int(crop.width * .08), int(crop.height * .08),
                 int(crop.width * .92), int(crop.height * .92))
        inner = crop.crop(inset) if inset[2] > inset[0] and inset[3] > inset[1] else crop
        color = estimate_dominant_color(inner)
        pad_x, pad_y = max(2, int(crop.width * .06)), max(2, int(crop.height * .06))
        ocr_crop = image.crop((max(0, x1 - pad_x), max(0, y1 - pad_y),
                               min(image.width, x2 + pad_x), min(image.height, y2 + pad_y)))
        brand_candidates, text_candidates = read_text_candidates(ocr_crop, category)
    else:
        color, brand_candidates, text_candidates = None, [], []

    return {"category": category, "confidence": confidence, "color": color,
            "brand": brand_candidates[0] if brand_candidates else None,
            "brand_candidates": brand_candidates, "text_candidates": text_candidates,
            "bbox": (x1, y1, x2, y2), "source": "model",
            "message": "YOLO category suggestion; review it before saving."}


def estimate_dominant_color(image):
    """Estimate a basic color from pixels; return None for near-uniformly ambiguous images."""
    small = image.convert("RGB")
    small.thumbnail((80, 80))
    pixels = list(small.get_flattened_data())
    if not pixels:
        return None
    # Quantize colors into coarse bins, then classify the most frequent non-transparent pixel.
    counts = {}
    for pixel in pixels:
        key = tuple((channel // 32) * 32 + 16 for channel in pixel)
        counts[key] = counts.get(key, 0) + 1
    dominant = max(counts, key=counts.get)
    name = min(_COLOR_PROTOTYPES, key=lambda n: sum(
        (dominant[i] - _COLOR_PROTOTYPES[n][i]) ** 2 for i in range(3)))
    return name


def _prepare_ocr_images(image):
    """Upscale and enhance a crop so small, low-contrast print is easier to OCR."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    gray = ImageOps.grayscale(image)
    scale = min(4, max(2, 1200 // max(gray.size)))
    gray = gray.resize((gray.width * scale, gray.height * scale), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(gray)
    enhanced = ImageEnhance.Contrast(gray).enhance(1.8).filter(ImageFilter.SHARPEN)
    thresholded = enhanced.point(lambda value: 255 if value > 160 else 0)
    return enhanced, thresholded


@lru_cache(maxsize=1)
def _load_ocr_engine():
    """Load RapidOCR and its bundled ONNX models once per server process."""
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _rapidocr_candidates(images):
    engine = _load_ocr_engine()
    candidates = []
    for image in images:
        result, _ = engine(image)
        for line in result or []:
            if len(line) >= 3:
                candidates.append((str(line[1]), float(line[2]) * 100))
    return candidates


def _ocr_candidate_lines(data):
    """Extract both individual words and grouped text lines from Tesseract output."""
    groups = defaultdict(list)
    tokens = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = re.sub(r"[^\w&+.-]", "", str(raw_text), flags=re.UNICODE).strip("._-")
        try:
            confidence = float(data.get("conf", [])[index])
        except (IndexError, TypeError, ValueError):
            continue
        if len(text) < 2 or confidence < 20:
            continue
        # Exclude isolated punctuation/numeric noise while retaining names like 3M.
        if not re.search(r"[a-z]", text, re.IGNORECASE):
            continue
        tokens.append((text, confidence))
        key = tuple(data.get(field, [0] * len(data.get("text", [])))[index]
                    for field in ("block_num", "par_num", "line_num"))
        groups[key].append((text, confidence))

    results = list(tokens)
    for words in groups.values():
        if len(words) > 1:
            line = " ".join(word for word, _ in words)
            mean_confidence = sum(conf for _, conf in words) / len(words)
            results.append((line, mean_confidence))
    return results


def _normalize_candidate(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _rank_candidates(scored_candidates, category=None):
    """Rank OCR text, then return brand names supported by category-aware OCR evidence."""
    scores = defaultdict(float)
    originals = {}
    for text, confidence in scored_candidates:
        cleaned = " ".join(text.split())[:40]
        normalized = _normalize_candidate(cleaned)
        if len(normalized) < 2:
            continue
        scores[normalized] = max(scores[normalized], confidence)
        originals.setdefault(normalized, cleaned)

    ranked_text = sorted(scores, key=lambda value: scores[value], reverse=True)
    brands = BRANDS_BY_CATEGORY.get(category, ALL_KNOWN_BRANDS)
    brand_scores = {}
    for brand in brands:
        brand_normalized = _normalize_candidate(brand)
        best = 0.0
        for text, ocr_score in scores.items():
            canonical = _BRAND_LOOKUP.get(text)
            if canonical == brand:
                best = max(best, ocr_score)
                continue
            if min(len(text), len(brand_normalized)) <= 3:
                similarity = 1.0 if text == brand_normalized else 0.0
            else:
                similarity = SequenceMatcher(None, text, brand_normalized).ratio()
            # For short acronyms such as HP, only an exact read should count.
            minimum_similarity = .72 if len(brand_normalized) >= 5 else .95
            if similarity >= minimum_similarity:
                best = max(best, ocr_score * similarity)
        if best:
            brand_scores[brand] = best
    ranked_brands = sorted(brand_scores, key=brand_scores.get, reverse=True)[:5]
    return ranked_brands, [originals[value] for value in ranked_text[:5]]


def read_text_candidates(image, category=None):
    """Return (brand candidates, raw OCR text candidates) using local ONNX OCR."""
    variants = _prepare_ocr_images(image)
    try:
        candidates = _rapidocr_candidates(variants)
        return _rank_candidates(candidates, category)
    except ImportError:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError:
            return [], []
        candidates = []
        for variant in variants:
            for page_segmentation in (6, 11, 12):
                try:
                    data = pytesseract.image_to_data(
                        variant, output_type=Output.DICT,
                        config=f"--oem 3 --psm {page_segmentation}")
                except (OSError, RuntimeError):
                    continue
                candidates.extend(_ocr_candidate_lines(data))
        return _rank_candidates(candidates, category)


def _fallback_image_analysis(image, message):
    """Keep OCR/color suggestions available when YOLO cannot produce a box.

    Color is sampled from a centered crop to reduce, but not eliminate, background
    influence. Without a detected class, OCR is checked against all known brand names.
    """
    width, height = image.size
    center = image.crop((int(width * .2), int(height * .2), int(width * .8), int(height * .8)))
    color = estimate_dominant_color(center) if center.width and center.height else None
    brand_candidates, text_candidates = read_text_candidates(image)
    return {"category": None, "confidence": None, "color": color,
            "brand": brand_candidates[0] if brand_candidates else None,
            "brand_candidates": brand_candidates, "text_candidates": text_candidates,
            "bbox": None, "source": "image-fallback", "message": message}


def _empty_result(message):
    return {"category": None, "confidence": None, "color": None, "brand": None,
            "brand_candidates": [], "text_candidates": [], "bbox": None,
            "source": "model", "message": message}
