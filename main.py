"""
SmartFind — An Intelligent Lost-and-Found Matching System for Campus Items
CS 403 prototype.   Run with:  streamlit run main.py

Perceive -> Reason -> Act
    PERCEIVE : smartfind_vision.py        (YOLO detector + crop-based color estimate + optional OCR)
  REASON   : smartfind_core.py          (working, rule-based similarity score out of 100)
    ACT      : auto_monitor_and_notify()  (persistent inbox + optional SMTP email)

Files (keep in the same folder):  main.py, smartfind_core.py, smartfind_vision.py, test_smartfind.py

Student/admin access uses verified OIDC identities. Admin role is granted only to
email addresses explicitly listed in Streamlit secrets.
"""
import base64
import hashlib
import inspect
import io
from datetime import date, datetime
from html import escape as _esc

import streamlit as st

from smartfind_core import (MATCH_THRESHOLD, NOTIFY_THRESHOLD, calculate_match_score,  # noqa: F401
                            find_pairs, new_notifications)
from smartfind_auth import create_guest_credentials, guest_code_digest, resolve_role
from smartfind_vision import (MODEL_LABELS, MODEL_PATHS, TRAINED_CATEGORIES,
                              brands_for_category, classify_image, normalize_brand,
                              normalize_brand_candidates, normalize_category)
from smartfind_store import (delete_report, load_notifications, load_reports,
                             fail_stuck_notification_emails, mark_all_notifications_read,
                             mark_notification_read,
                             notification_keys, pending_notification_emails,
                             claim_notification_email, finish_notification_email,
                             configure_supabase, initialize_storage,
                             create_guest_account, find_guest_account,
                             load_user_preferences, save_user_preferences,
                             load_report_draft, save_report_draft, delete_report_draft,
                             retry_notification_email, save_notifications, save_report,
                             )
from smartfind_mail import SMTPDeliveryError, is_configured, send_match_email, test_smtp_connection
from smartfind_theme import theme_variables_css

st.set_page_config(page_title="SmartFind - Campus Lost & Found", page_icon="🔎",
                   layout="wide", initial_sidebar_state="auto")

st.session_state.setdefault("ui_theme", "light")
st.markdown(f"""
<style>
{theme_variables_css(st.session_state.ui_theme)}
.stApp {{ background:var(--sf-bg); color:var(--sf-text); }}
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p,
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p {{ color:var(--sf-text) !important; }}
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"],
[data-testid="stDateInput"] [role="group"], [data-testid="stSelectbox"] [role="group"] {{
  background:var(--sf-surface) !important; border:1px solid var(--sf-border) !important;
  border-radius:10px !important;
}}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input, [data-testid="stSelectbox"] [role="group"] * {{
  color:var(--sf-text) !important; background:transparent !important; caret-color:var(--sf-accent) !important;
}}
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {{
  color:var(--sf-muted) !important; opacity:1 !important;
}}
.stButton > button, [data-testid="stFormSubmitButton"] button {{
  min-height:44px; border-radius:10px; transition:transform .18s ease, box-shadow .18s ease, background-color .18s ease;
}}
:focus-visible {{ outline:3px solid var(--sf-accent) !important; outline-offset:2px !important; }}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation-duration:.01ms !important; animation-iteration-count:1 !important;
    scroll-behavior:auto !important; transition-duration:.01ms !important; }}
}}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# Compatibility check: tests the APIs this app actually uses.
# Recommended: Streamlit >= 1.40 (st.container(key=), st.dialog, selectbox(index=None)).
# ------------------------------------------------------------
def _check_streamlit():
    missing = []
    if "key" not in inspect.signature(st.container).parameters:
        missing.append("st.container(key=...)")
    for name in ("dialog", "rerun", "camera_input"):
        if not hasattr(st, name):
            missing.append(f"st.{name}")
    if "placeholder" not in inspect.signature(st.selectbox).parameters:
        missing.append("st.selectbox(index=None, placeholder=...)")
    if missing:
        st.error(f"This Streamlit version ({st.__version__}) is too old for SmartFind. Missing: "
                 f"{', '.join(missing)}. Run:  pip install -U \"streamlit>=1.40\"")
        st.stop()


_check_streamlit()
# Full-width buttons: newer Streamlit uses width="stretch", older uses **STRETCH.
def _stretch(fn):
    return {"width": "stretch"} if "width" in inspect.signature(fn).parameters else {"use_container_width": True}


STRETCH = _stretch(st.button)
STRETCH_SUBMIT = _stretch(st.form_submit_button)


def _current_user():
    try:
        auth_config = dict(st.secrets.get("auth", {}))
        app_config = dict(st.secrets.get("smartfind", {}))
        supabase_config = dict(st.secrets.get("supabase", {}))
    except Exception:
        auth_config, app_config, supabase_config = {}, {}, {}

    if not getattr(st.user, "is_logged_in", False):
        configure_supabase(supabase_config.get("database_url", ""))
        if not str(supabase_config.get("database_url", "")).strip():
            st.error("Supabase database_url is required; SQLite storage is no longer supported.")
            st.info("Add [supabase].database_url to Streamlit Secrets before using SmartFind.")
            st.stop()

        guest_id = st.session_state.get("guest_account_id")
        if guest_id:
            st.session_state.pop("guest_recovery_input", None)
            return {"email": f"guest:{guest_id}", "name": "Guest", "role": "student",
                    "is_guest": True, "supabase_database_url": supabase_config.get("database_url", "")}

        st.markdown('<div class="page-title">SmartFind sign in</div>', unsafe_allow_html=True)
        st.caption("Sign in with a verified campus account or continue as a guest. Guests can submit reports and receive in-app match notifications.")
        required_auth = ("redirect_uri", "cookie_secret", "client_id", "client_secret",
                         "server_metadata_url")
        oidc_configured = all(str(auth_config.get(key, "")).strip() for key in required_auth)
        if oidc_configured:
            st.button("Continue with Google", on_click=st.login, type="primary")
        else:
            st.info("Google sign-in is unavailable until OIDC is configured. You can still continue as a guest.")

        if st.button("Continue as guest"):
            guest_id, recovery_code, code_hash = create_guest_credentials()
            create_guest_account(guest_id, code_hash)
            st.session_state.guest_account_id = guest_id
            st.session_state.guest_recovery_code = recovery_code
            st.rerun()

        st.markdown("#### Return to a guest account")
        recovery_code = st.text_input("Guest recovery code", type="password", key="guest_recovery_input")
        if st.button("Resume guest account"):
            code_hash = guest_code_digest(recovery_code)
            guest_id = find_guest_account(code_hash) if code_hash else None
            if guest_id:
                st.session_state.guest_account_id = guest_id
                st.rerun()
            st.error("That recovery code is invalid. Check it and try again.")
        st.stop()

    required_auth = ("redirect_uri", "cookie_secret", "client_id", "client_secret",
                     "server_metadata_url")
    if any(not str(auth_config.get(key, "")).strip() for key in required_auth):
        st.error("Sign-in is not configured yet. An administrator must add the OIDC settings to Streamlit secrets.")
        st.info("Configure the [auth] and [smartfind] sections using the setup instructions in README.md.")
        st.stop()

    st.session_state.pop("guest_account_id", None)
    st.session_state.pop("guest_recovery_code", None)
    email = str(st.user.get("email", "")).strip().casefold()
    role = resolve_role(email, st.user.get("email_verified", False),
                        app_config.get("student_email_domains", []),
                        app_config.get("admin_emails", []))
    if role is None:
        st.error("This verified account is not authorized to use SmartFind.")
        st.button("Sign out", on_click=st.logout)
        st.stop()
    return {"email": email, "name": st.user.get("name") or email, "role": role, "is_guest": False,
            "supabase_database_url": supabase_config.get("database_url", "")}


current_user = _current_user()
configure_supabase(current_user["supabase_database_url"])
if not str(current_user["supabase_database_url"]).strip():
    st.error("Supabase database_url is required; SQLite storage is no longer supported.")
    st.info("Add [supabase].database_url to Streamlit Secrets before using SmartFind.")
    st.stop()
# Schema setup is an explicit, one-time migration step per app process.  Query
# functions below only open a short-lived connection for their own operation.
initialize_storage()

if st.session_state.get("preferences_loaded_for") != current_user["email"]:
    previous_owner = st.session_state.get("preferences_loaded_for")
    if previous_owner and previous_owner != current_user["email"]:
        for state_key in list(st.session_state):
            if state_key.startswith(("report_", "photo_mode_", "photo_upload_", "photo_camera_")):
                st.session_state.pop(state_key, None)
        st.session_state.pop("flash", None)
        st.session_state.page = "Home"
    stored_preferences = load_user_preferences(current_user["email"])
    st.session_state.ui_preferences = stored_preferences
    st.session_state.ui_theme = stored_preferences.get("theme", "light")
    if st.session_state.ui_theme not in ("light", "dark"):
        st.session_state.ui_theme = "light"
    st.session_state.records_search = stored_preferences.get("records_search", "")
    st.session_state.records_type_filter = stored_preferences.get("records_type_filter", "Lost & Found")
    st.session_state.records_category_filter = stored_preferences.get(
        "records_category_filter", "All categories")
    st.session_state.records_status_filter = stored_preferences.get(
        "records_status_filter", "All statuses")
    st.session_state.theme_dark = st.session_state.ui_theme == "dark"
    st.session_state.mobile_theme_dark = st.session_state.ui_theme == "dark"
    st.session_state.preferences_loaded_for = current_user["email"]

if st.session_state.get("drafts_loaded_for") != current_user["email"]:
    st.session_state.report_drafts = {
        report_type: load_report_draft(current_user["email"], report_type)
        for report_type in ("Lost", "Found")
    }
    st.session_state.drafts_loaded_for = current_user["email"]


def persist_ui_preferences(**updates):
    preferences = dict(st.session_state.get("ui_preferences", {}))
    preferences.update(updates)
    if preferences != st.session_state.get("ui_preferences", {}):
        save_user_preferences(current_user["email"], preferences)
        st.session_state.ui_preferences = preferences


def update_theme_preference(widget_key):
    selected_theme = "dark" if st.session_state[widget_key] else "light"
    st.session_state.ui_theme = selected_theme
    st.session_state.theme_dark = selected_theme == "dark"
    st.session_state.mobile_theme_dark = selected_theme == "dark"
    persist_ui_preferences(theme=selected_theme)


def persist_report_draft(report_type, payload):
    save_report_draft(current_user["email"], report_type, payload)
    st.session_state.report_drafts[report_type] = dict(payload)


def remove_report_draft(report_type):
    delete_report_draft(current_user["email"], report_type)
    st.session_state.report_drafts[report_type] = None
    st.session_state[f"report_wizard_step_{report_type}"] = 1
    for field in ("category", "brand", "manual_brand", "name", "color", "location",
                  "description", "date"):
        st.session_state.pop(f"report_{field}_{report_type}", None)


def clear_records_filters():
    defaults = {
        "records_search": "",
        "records_type_filter": "Lost & Found",
        "records_category_filter": "All categories",
        "records_status_filter": "All statuses",
    }
    st.session_state.update(defaults)
    persist_ui_preferences(records_search="", records_type_filter="Lost & Found",
                           records_category_filter="All categories",
                           records_status_filter="All statuses")


def sign_out():
    if current_user["is_guest"]:
        st.session_state.pop("guest_account_id", None)
        st.session_state.pop("guest_recovery_code", None)
        st.session_state.pop("guest_recovery_input", None)
        st.session_state.page = "Home"
        st.rerun()
    else:
        st.logout()


# ============================================================
# CONFIGURATION  (edit here — nothing else needs to change)
# ============================================================

# Categories come from the trained model; all remain user-confirmable.
MANUAL_ONLY_CATEGORIES = {"Smartphone": "📱", "ID Card": "🪪", "Earphones": "🎧", "Keys": "🔑",
                          "Eyeglasses": "👓", "Water Bottle": "🧴", "Umbrella": "☂️", "Other": "📦"}

MODEL_CATEGORIES = list(TRAINED_CATEGORIES)
AI_CATEGORIES = {name: {"icon": "🔎"} for name in MODEL_CATEGORIES}
ALL_CATEGORIES = list(dict.fromkeys(
    MODEL_CATEGORIES + [normalize_category(name) for name in MANUAL_ONLY_CATEGORIES]))
CATEGORY_ICONS = {**{k: v["icon"] for k, v in AI_CATEGORIES.items()},
                  **{normalize_category(k): v for k, v in MANUAL_ONLY_CATEGORIES.items()}}

PAGES = [
    ("Home", "⌂"),
    ("Report Lost Item", "ⓘ"),
    ("Report Found Item", "⌕"),
    ("Lost & Found Records", "▤"),
    ("Possible Matches", "⛓"),
    ("Notifications", "🔔"),
]
if current_user["role"] == "admin":
    PAGES.append(("Admin Management", "♙"))
if st.session_state.get("page") == "Admin Management" and current_user["role"] != "admin":
    st.session_state.page = "Home"
if st.session_state.get("page") not in [name for name, _ in PAGES]:
    st.session_state.page = "Home"

# ============================================================
# HELPERS
# ============================================================

def html(s):
    """Render an HTML block. Indentation/blank lines are stripped so Markdown
    never turns the HTML into a code block."""
    s = "\n".join(l.strip() for l in s.splitlines() if l.strip())
    st.markdown(s, unsafe_allow_html=True)


def esc(text):
    """Escape user text before putting it in HTML ($ is escaped so Streamlit
    doesn't treat it as LaTeX)."""
    return _esc(str(text)).replace("\n", " ").replace("$", "&#36;")


def navigate(page):
    st.session_state.page = page
    st.rerun()


def next_id():
    """IDs are never reused, even after a delete (a reused ID could hide a new notification)."""
    st.session_state.id_counter += 1
    return f"SF-2026-{st.session_state.id_counter:03d}"


def current_pairs():
    # Include legacy records loaded from older databases before score calculation.
    for report in st.session_state.reports:
        report.setdefault("brand", "")
    return find_pairs(st.session_state.reports)


def get_report(rid):
    return next((r for r in st.session_state.reports if r["id"] == rid), None)


def make_thumbnail(image_bytes):
    """Shrink a photo to a small JPEG data-URI so it can be stored and shown anywhere."""
    try:
        from PIL import Image, ImageOps
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(image_bytes))).convert("RGB")
        img.thumbnail((420, 420))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def analyze_photo(image_bytes, model_version):
    """Cache model/OCR work across Streamlit reruns for the same uploaded photo."""
    return classify_image(image_bytes, model_version=model_version)


def thumb(r, size=44):
    """Photo thumbnail if the report has one, otherwise a category icon tile."""
    if r.get("photo"):
        return (f'<img src="{r["photo"]}" style="width:{size}px;height:{size}px;object-fit:cover;'
                f'border-radius:8px;flex-shrink:0">')
    icon = CATEGORY_ICONS.get(r["category"], "📦")
    return (f'<div style="width:{size}px;height:{size}px;border-radius:8px;background:#edf2f7;display:flex;'
            f'align-items:center;justify-content:center;font-size:{int(size * .5)}px;flex-shrink:0">{icon}</div>')


def type_pill(r):
    cls = "pill-lost" if r["type"] == "Lost" else "pill-found"
    return f'<span class="pill {cls}">{r["type"]}</span>'


def fmt_date(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return d


def render_report_wizard(report_type):
    is_lost = report_type == "Lost"
    verb = "lost" if is_lost else "found"
    draft = st.session_state.report_drafts.get(report_type) or {}
    step_key = f"report_wizard_step_{report_type}"
    st.session_state.setdefault(step_key, draft.get("step", 1))
    if st.session_state[step_key] not in (1, 2, 3):
        st.session_state[step_key] = 1
    step = st.session_state[step_key]
    nonce = st.session_state.nonce

    html(f"""<div class="eyebrow">NEW {report_type.upper()} REPORT</div>
    <div class="page-title">Report {report_type.lower()} item</div>
    <div class="page-sub">Add a photo if you have one, describe the item, then review before publishing.</div>""")
    st.progress(step / 3, text=f"Step {step} of 3 · {('Photo' if step == 1 else 'Details' if step == 2 else 'Review')}")

    with st.container(key="card_form"):
        if draft:
            st.info("A private draft for this report type is saved to your account.")
            if st.button("Discard saved draft", key=f"discard_draft_{report_type}"):
                remove_report_draft(report_type)
                st.rerun()

        if step == 1:
            st.markdown("#### 1 · Add a photo")
            st.caption("Optional. Photo analysis suggests item details; review and correct all suggestions.")
            st.selectbox("Photo detector model", options=list(MODEL_LABELS),
                         format_func=MODEL_LABELS.__getitem__, key="vision_model",
                         help="This choice only changes photo analysis in your session.")
            upload_mode, camera_mode, no_photo = "Choose / upload", "Take photo", "Continue without photo"
            mode = st.radio("Photo source", [upload_mode, camera_mode, no_photo],
                            horizontal=True, key=f"photo_mode_{report_type}_{nonce}")
            photo_file = None
            if mode == upload_mode:
                photo_file = st.file_uploader("Item photo", type=["jpg", "jpeg", "png"],
                                              key=f"photo_upload_{report_type}_{nonce}")
            elif mode == camera_mode:
                photo_file = st.camera_input("Take a photo", key=f"photo_camera_{report_type}_{nonce}")

            photo_bytes = photo_file.getvalue() if photo_file else None
            photo_uri = make_thumbnail(photo_bytes) if photo_bytes else draft.get("photo")
            suggestion = draft.get("suggestion")
            if photo_bytes:
                try:
                    with st.spinner("Analyzing the photo…"):
                        suggestion = analyze_photo(photo_bytes, st.session_state.vision_model)
                except (NotImplementedError, FileNotFoundError, RuntimeError, ValueError) as exc:
                    suggestion = {"category": None, "confidence": None, "color": None,
                                  "brand": None, "brand_candidates": [], "text_candidates": [],
                                  "message": str(exc)}
                    st.warning(f"Photo analysis is unavailable: {esc(exc)}. You can still enter the report manually.")

            if photo_uri:
                html(f'<img src="{photo_uri}" alt="Report photo preview" '
                     'style="width:140px;height:140px;object-fit:cover;border-radius:12px">')
            if suggestion:
                detected = suggestion.get("category") or "No supported item detected"
                st.caption(f"Suggestion: {detected}. Confirm or change suggestions in the next step.")

            if st.button("Continue to details", type="primary", key=f"photo_next_{report_type}"):
                persist_report_draft(report_type, {
                    **draft, "step": 2, "photo": photo_uri, "suggestion": suggestion,
                    "vision_model": st.session_state.vision_model,
                })
                st.session_state[step_key] = 2
                st.rerun()

        elif step == 2:
            st.markdown("#### 2 · Describe the item")
            st.caption("Your draft is private to your account until you explicitly submit it.")
            suggestion = draft.get("suggestion") or {}
            suggested_category = suggestion.get("category")
            category_key = "report_category_" + report_type
            if st.session_state.get(category_key) not in ALL_CATEGORIES:
                st.session_state[category_key] = (
                    draft.get("category") or (
                        suggested_category if suggested_category in ALL_CATEGORIES else None))
                if st.session_state[category_key] not in ALL_CATEGORIES:
                    st.session_state[category_key] = None
            cat = st.selectbox("Item category *", ALL_CATEGORIES, index=None,
                               placeholder="Select a category", key=category_key)

            brand_candidates = normalize_brand_candidates(
                suggestion.get("brand_candidates", []), suggestion.get("brand"))
            brand_options = ["Unknown / no visible brand"] + list(dict.fromkeys(
                brand_candidates + brands_for_category(cat))) + ["Other / not listed"]
            brand_key = "report_brand_" + report_type
            if st.session_state.get(brand_key) not in brand_options:
                st.session_state[brand_key] = (
                    draft.get("brand") if draft.get("brand") in brand_options else
                    "Other / not listed" if draft.get("brand") else
                    next((value for value in brand_candidates if value in brand_options),
                         "Unknown / no visible brand"))
            brand_choice = st.selectbox("Brand (optional)", brand_options, key=brand_key)
            manual_brand = ""
            if brand_choice == "Other / not listed":
                manual_key = f"report_manual_brand_{report_type}"
                st.session_state.setdefault(manual_key, draft.get("brand", ""))
                manual_brand = st.text_input("Enter brand name", key=manual_key)
            brand_value = normalize_brand(manual_brand) if manual_brand.strip() else ""
            if brand_choice not in ("Unknown / no visible brand", "Other / not listed"):
                brand_value = normalize_brand(brand_choice)

            defaults = {
                "name": draft.get("name", ""),
                "color": draft.get("color", suggestion.get("color") or ""),
                "location": draft.get("location", ""),
                "description": draft.get("description", ""),
            }
            for field, value in defaults.items():
                st.session_state.setdefault(f"report_{field}_{report_type}", value)
            draft_date = draft.get("date")
            try:
                date_default = datetime.strptime(draft_date, "%Y-%m-%d").date() if draft_date else date.today()
            except ValueError:
                date_default = date.today()
            date_key = f"report_date_{report_type}"
            if date_key not in st.session_state:
                st.session_state[date_key] = date_default

            with st.form(f"report_details_{report_type}_{nonce}"):
                name = st.text_input("Item name (optional)", key=f"report_name_{report_type}",
                                     placeholder="e.g. Black smartphone")
                color = st.text_input("Color (optional)", key=f"report_color_{report_type}",
                                      placeholder="e.g. Black")
                location = st.text_input(
                    f"Where was it {'last seen' if is_lost else 'found'}? *",
                    key=f"report_location_{report_type}",
                    placeholder="e.g. Q-5312, Library 2nd Floor")
                report_date = st.date_input(f"Date {verb} *", max_value=date.today(),
                                            key=date_key)
                description = st.text_area("Description (optional)",
                                           key=f"report_description_{report_type}",
                                           placeholder="Distinctive marks, case, stickers, or scratches")
                st.caption("Drafts are private and are not published until you submit.")
                back = st.form_submit_button("Back to photo")
                review = st.form_submit_button("Save draft and review", type="primary",
                                               **STRETCH_SUBMIT)

            if back or review:
                errors = []
                if review and not cat:
                    errors.append("Please choose an item category.")
                if review and not location.strip():
                    errors.append(f"Please enter where the item was {'last seen' if is_lost else 'found'}.")
                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    payload = {
                        **draft, "step": 1 if back else 3, "photo": draft.get("photo"),
                        "suggestion": suggestion, "category": cat, "brand": brand_value,
                        "name": name.strip(), "color": color.strip(), "location": location.strip(),
                        "date": report_date.strftime("%Y-%m-%d"), "description": description.strip(),
                        "vision_model": st.session_state.vision_model,
                    }
                    persist_report_draft(report_type, payload)
                    st.session_state[step_key] = payload["step"]
                    st.rerun()

        else:
            st.markdown("#### 3 · Review and submit")
            st.caption("Check the details before publishing this report.")
            st.write(f"**Type:** {report_type}")
            st.write(f"**Item:** {draft.get('name') or draft.get('category') or '—'}")
            st.write(f"**Category:** {draft.get('category') or '—'}")
            st.write(f"**Brand:** {draft.get('brand') or '—'}")
            st.write(f"**Color:** {draft.get('color') or '—'}")
            st.write(f"**Location:** {draft.get('location') or '—'}")
            st.write(f"**Date:** {draft.get('date') or '—'}")
            st.write(f"**Description:** {draft.get('description') or '—'}")
            if draft.get("photo"):
                html(f'<img src="{draft["photo"]}" alt="Attached report photo" '
                     'style="width:140px;height:140px;object-fit:cover;border-radius:12px">')

            back_col, submit_col = st.columns(2)
            if back_col.button("Back to details", key=f"review_back_{report_type}"):
                draft["step"] = 2
                persist_report_draft(report_type, draft)
                st.session_state[step_key] = 2
                st.rerun()
            if submit_col.button("Submit report", type="primary", key=f"report_submit_{report_type}"):
                item_name = str(draft.get("name", "")).strip()
                if not item_name:
                    item_name = f"{draft.get('color', '').strip()} {draft.get('category', '')}".strip()
                rid = next_id()
                report = {
                    "id": rid, "type": report_type, "item": item_name,
                    "category": draft["category"], "color": draft.get("color", ""),
                    "brand": draft.get("brand", ""), "location": draft["location"],
                    "date": draft["date"], "description": draft.get("description", ""),
                    "photo": draft.get("photo"),
                    "status": "Searching" if is_lost else "Reported",
                    "user_email": current_user["email"],
                }
                st.session_state.reports.append(report)
                save_report(report)
                remove_report_draft(report_type)
                before = len(st.session_state.notifications)
                auto_monitor_and_notify()
                n_matches = sum(1 for pair in current_pairs() if rid in (pair[1]["id"], pair[2]["id"]))
                message = f"Report {rid} saved. "
                if n_matches:
                    message += f"SmartFind found {n_matches} possible match(es) — see Possible Matches."
                    if len(st.session_state.notifications) > before:
                        message += " A new inbox notification was created."
                else:
                    message += "No possible matches yet — SmartFind will compare it with new reports as they arrive."
                st.session_state.flash = ("success", message)
                st.session_state.nonce += 1
                st.rerun()


# ============================================================
# SESSION STATE  (Supabase is read once per signed-in session, not per navigation)
# ============================================================

st.session_state.setdefault("page", "Home")
st.session_state.setdefault("nonce", 0)          # bumped after a submit to reset the form
st.session_state.setdefault("vision_model", "v1")
if not st.session_state.get("reports_loaded", False):
    st.session_state.reports = load_reports()
    st.session_state.reports_loaded = True
st.session_state.setdefault("reports", [])
st.session_state.setdefault("id_counter", 0)
for _report in st.session_state.reports:
    _stored_brand = _report.get("brand", "")
    _stored_category = _report.get("category", "")
    _report["brand"] = normalize_brand(_stored_brand)
    _report["category"] = normalize_category(_stored_category)
    if _report["brand"] != _stored_brand or _report["category"] != _stored_category:
        save_report(_report)
st.session_state.id_counter = max(
    st.session_state.id_counter,
    max((int(r["id"].split("-")[-1]) for r in st.session_state.reports), default=0))

# ============================================================
# AGENT 1 — PERCEIVE: see smartfind_vision.py (YOLO detection, crop analysis, optional OCR)
# ============================================================

# ============================================================
# AGENT 2 — REASON: see smartfind_core.py (rule-based similarity score out of 100)
# ============================================================

# ============================================================
# AGENT 3 — ACT   (persistent per-owner inbox notifications; no email is sent)
# ============================================================

def deliver_pending_notification_emails():
    """Deliver queued email without recalculating every report pair."""
    if current_user["is_guest"]:
        return
    fail_stuck_notification_emails()
    if not is_configured(mail_config):
        return
    for notification in pending_notification_emails():
        if not claim_notification_email(notification["id"]):
            continue
        try:
            send_match_email(notification, mail_config)
        except Exception as exc:
            finish_notification_email(notification["id"], "failed",
                                      error=f"{type(exc).__name__}: {exc}")
        else:
            finish_notification_email(notification["id"], "sent",
                                      timestamp=datetime.now().isoformat(timespec="seconds"))


def auto_monitor_and_notify():
    """Recalculate matches only after a report or its status has changed."""
    notifications = new_notifications(
        st.session_state.reports, notification_keys(), datetime.now().strftime("%b %d, %I:%M %p"))
    save_notifications(notifications)
    if not current_user["is_guest"]:
        deliver_pending_notification_emails()
    st.session_state.notifications = load_notifications(current_user["email"])


try:
    mail_config = dict(st.secrets.get("mail", {}))
except Exception:
    mail_config = {}

if st.session_state.get("notifications_loaded_for") != current_user["email"]:
    st.session_state.notifications = load_notifications(current_user["email"])
    st.session_state.notifications_loaded_for = current_user["email"]
st.session_state.setdefault("notifications", [])

# ============================================================
# CSS
# ============================================================

active = st.session_state.page
active_idx = [p for p, _ in PAGES].index(active)

# ------------------------------------------------------------
# TEXT CONTRAST
# Cause of the "white text on white card" bug: the app paints its own light surfaces
# (white cards, light page background) but never set a text color. Streamlit's default
# text color follows the user's OS/browser theme, which is WHITE in dark mode. So every
# label/heading/caption/radio option that Streamlit draws itself became white-on-white.
# Fix: force dark text ONLY on elements that sit directly on the surfaces we paint white.
# Inputs, dropdown menus and other themed widgets keep their own (self-consistent) colors,
# and our own HTML keeps its inline colors (descendants with their own color are unaffected).
# ------------------------------------------------------------
NAVY, SLATE = "#0d2847", "#4a5568"
LIGHT_SURFACES = ['div[class*="st-key-card_"]',                   # all white cards
                  '[data-testid="stDialog"] div[role="dialog"]',  # dialogs (forced white below)
                  '[data-testid="stExpander"]']                   # expanders (forced white below)


def _on_light(suffixes, rules):
    sel = ", ".join(f"{surface} {suffix}".strip() for surface in LIGHT_SURFACES for suffix in suffixes)
    return f"{sel} {{ {rules} }}\n"


_MD = '[data-testid="stMarkdownContainer"]'
_BTN = ['[data-testid^="stBaseButton-secondary"]', '.stButton > button']
light_css = "".join([
    # headings, paragraphs, list items rendered by st.markdown / st.write / st.info etc.
    _on_light([_MD] + [f"{_MD} {t}" for t in ("p", "li", "h1", "h2", "h3", "h4", "h5", "h6")],
              f"color:{NAVY} !important;"),
    # form labels (text_input, selectbox, date_input, text_area, radio titles...)
    _on_light(['[data-testid="stWidgetLabel"]', '[data-testid="stWidgetLabel"] p',
               '[data-testid="stWidgetLabel"] label'], f"color:{NAVY} !important; font-weight:600;"),
    # radio option labels
    _on_light(['[data-testid="stRadio"] label', '[data-testid="stRadio"] label p'],
              f"color:{NAVY} !important;"),
    # st.caption descriptions
    _on_light(['[data-testid="stCaptionContainer"]', '[data-testid="stCaptionContainer"] p'],
              f"color:{SLATE} !important;"),
    # normal buttons: white with navy text (primary buttons keep the theme's primary color)
    _on_light(_BTN, f"background:#fff !important; color:{NAVY} !important; border:1px solid #cbd5e0 !important;"),
    _on_light([f"{b} p" for b in _BTN], f"color:{NAVY} !important;"),
    _on_light([f"{b}:hover" for b in _BTN], "border-color:#2aa99b !important;"),
    _on_light([f"{b}:disabled" for b in _BTN], "color:#a0aec0 !important; background:#f7fafc !important;"),
])

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
.stApp {{ background:#f4f7fb; }}

/* Streamlit's current React-Aria roots inherit the OS theme unless styled directly. */
[data-testid="stTextInputRootElement"],
[data-testid="stTextAreaRootElement"],
[data-testid="stDateInput"] [role="group"],
[data-testid="stSelectbox"] [role="group"] {{
    background:#fff !important; border:1px solid #cbd5e0 !important; border-radius:8px !important;
    box-shadow:none !important;
}}
[data-testid="stTextInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stDateInput"] input,
[data-testid="stDateInput"] [role="spinbutton"],
[data-testid="stSelectbox"] [role="group"] * {{
    background-color:transparent !important; color:#0d2847 !important; caret-color:#2a9d8f !important;
}}
[data-testid="stTextInput"] input::placeholder,
[data-testid="stTextArea"] textarea::placeholder,
[data-testid="stDateInput"] input::placeholder {{ color:#718096 !important; opacity:1 !important; }}
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stTextAreaRootElement"]:focus-within,
[data-testid="stDateInput"] [role="group"]:focus-within,
[data-testid="stSelectbox"] [role="group"]:focus-within {{
    border-color:#2a9d8f !important; box-shadow:0 0 0 1px #2a9d8f !important;
}}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="popover"] [role="option"] {{
    background:#fff !important; color:#0d2847 !important;
}}
[data-baseweb="popover"] [role="option"]:hover {{ background:#e6fffa !important; }}

/* Hide Streamlit chrome but keep the sidebar toggle */
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stToolbar"] {{ display:none !important; }}
header[data-testid="stHeader"] {{ background:transparent; height:0; }}
.block-container {{ padding:0 0 3rem 0 !important; max-width:100% !important; }}
.st-key-body_pad {{ padding:0 35px; }}

/* Sidebar */
section[data-testid="stSidebar"], section[data-testid="stSidebar"] > div {{ background:#0d2847 !important; }}
section[data-testid="stSidebar"] {{ min-width:260px !important; max-width:260px !important; }}
section[data-testid="stSidebar"] .stButton > button {{
  width:100%; justify-content:flex-start; border:1px solid transparent; background:transparent;
  color:#d1e2f2; font-size:13px; font-weight:600; border-radius:10px; padding:10px 14px; box-shadow:none; }}
section[data-testid="stSidebar"] .stButton > button > div {{ width:100%; justify-content:flex-start !important; }}
section[data-testid="stSidebar"] .stButton > button p {{ text-align:left !important; width:100%; }}
section[data-testid="stSidebar"] .stButton > button:hover {{ background:rgba(255,255,255,.08); color:#fff; }}
.st-key-nav_{active_idx} button {{
  background:rgba(42,169,155,.18) !important; color:#fff !important; border:1px solid #2aa99b !important; }}
.logo-row {{ display:flex; align-items:center; gap:12px; padding:24px 8px 18px; border-bottom:1px solid rgba(255,255,255,.08); }}
.logo-icon {{ width:44px; height:44px; border-radius:12px; background:#2aa99b; color:#fff; display:flex;
  align-items:center; justify-content:center; font-weight:800; font-size:18px; }}
.menu-label {{ color:#6482a0; font-size:10px; font-weight:800; letter-spacing:1px; padding:20px 8px 8px; }}

/* Top header */
.top-header {{ height:60px; background:#fff; border-bottom:1px solid #e2e8f0; display:flex;
  align-items:center; justify-content:space-between; padding:0 35px; margin-bottom:24px; }}
.breadcrumb {{ color:#718096; font-size:13px; }} .breadcrumb strong {{ color:#1a202c; }}
.user-avatar {{ width:32px; height:32px; border-radius:50%; background:#e2e8f0; color:#2b6cb0;
  display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; }}

/* Cards: any container whose key starts with card_ */
div[class*="st-key-card_"] {{ background:#fff; border:1px solid #e2e8f0; border-radius:14px; padding:22px; }}
div[class*="st-key-card_"] .stButton > button {{ border-radius:8px; font-weight:600; font-size:12px; }}

/* Hero */
.st-key-hero {{ background:linear-gradient(110deg,#0e2a47 0%,#15395f 55%,#1c525f 100%); border-radius:18px;
  padding:36px 40px; box-shadow:0 10px 25px rgba(13,40,71,.12); }}
.st-key-hero .stButton > button {{ border-radius:8px; font-weight:700; font-size:13px; }}
.st-key-hero_lost button {{ background:#2aa99b; color:#fff; border:none; }}
.st-key-hero_found button {{ background:transparent; color:#fff; border:1px solid rgba(255,255,255,.4); }}
.hero-badge {{ background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.2); border-radius:20px;
  padding:4px 12px; font-size:10px; font-weight:700; color:#e2e8f0; display:inline-block; margin-bottom:14px; }}
.hero-title {{ font-size:40px; font-weight:800; line-height:1.15; color:#fff; margin-bottom:12px; }}
.hero-title span {{ color:#2aa99b; }}
.hero-desc {{ color:#cddbe8; font-size:13px; line-height:1.6; margin-bottom:18px; max-width:520px; }}
.how-card {{ background:#fff; border-radius:14px; padding:20px; color:#1a202c; box-shadow:0 8px 20px rgba(0,0,0,.15); }}
.step {{ display:flex; gap:12px; margin-top:14px; }}
.step-num {{ width:24px; height:24px; border-radius:50%; background:#ebf8ff; color:#2b6cb0; font-weight:800;
  font-size:11px; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}

.eyebrow {{ color:#2a9d8f; font-size:11px; font-weight:800; letter-spacing:1px; }}
.page-title {{ font-size:30px; font-weight:500; color:#0d2847; margin:2px 0 4px; }}
.page-sub {{ color:#718096; font-size:13px; margin-bottom:18px; }}

.pill {{ padding:3px 12px; border-radius:12px; font-size:11px; font-weight:700; display:inline-block; }}
.pill-lost {{ background:#fffaf0; color:#dd6b20; border:1px solid #fbd38d; }}
.pill-found {{ background:#f0fff4; color:#2f855a; border:1px solid #9ae6b4; }}
.pill-open {{ background:#edf2f7; color:#4a5568; }}
.th {{ font-size:10px; font-weight:800; color:#718096; letter-spacing:.5px; }}
.notif-bar {{ background:#ebf8ff; border:1px solid #bee3f8; border-radius:12px; padding:12px 16px;
  margin-bottom:18px; color:#2a4365; font-size:12px; line-height:1.5; }}
{light_css}
/* Dialogs and expanders are themed dark in dark mode; make them white to match the cards */
[data-testid="stDialog"] div[role="dialog"] {{ background:#fff !important; }}
[data-testid="stDialog"] div[role="dialog"] h1, [data-testid="stDialog"] div[role="dialog"] h2,
[data-testid="stDialog"] div[role="dialog"] h3 {{ color:{NAVY} !important; }}
[data-testid="stDialog"] button[aria-label="Close"] {{ color:{SLATE} !important; }}
[data-testid="stExpander"] {{ background:#fff; border:1px solid #e2e8f0 !important; border-radius:12px; }}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p,
[data-testid="stExpander"] summary span {{ color:{NAVY} !important; }}
[data-testid="stExpander"] summary svg {{ fill:{NAVY} !important; color:{NAVY} !important; }}
/* Alerts (st.success / info / warning / error) sit on the light page: dark text on their tinted fill */
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] p,
[data-testid="stAlert"] [data-testid="stMarkdownContainer"] li {{ color:#1a202c !important; }}

.warn-bar {{ background:#fffaf0; border:1px solid #fbd38d; border-radius:12px; padding:12px 16px;
  margin-bottom:18px; color:#7b341e; font-size:12px; line-height:1.5; }}
.sim-tag {{ background:#fefcbf; color:#744210; font-size:9px; font-weight:800; padding:2px 7px;
  border-radius:6px; letter-spacing:.5px; margin-right:6px; }}
.lbl {{ display:none; color:#718096; font-size:12px; }}
.rid {{ font-size:10px; color:#a0aec0; }}
.stat-icon {{ width:34px; height:34px; border-radius:8px; background:#e6fffa; display:flex;
  align-items:center; justify-content:center; font-size:16px; flex-shrink:0; }}

/* Records list: table-like on desktop, stacked cards on phones */
.rec-head, .rec-summary {{ display:grid; grid-template-columns:3fr 1.3fr 1fr 1.8fr 1.3fr 1fr 1fr;
  gap:10px; align-items:center; }}
.rec-head {{ padding:8px 6px; border-bottom:1px solid #e2e8f0; }}
details.rec {{ border-bottom:1px solid #edf2f7; }}
details.rec > summary {{ list-style:none; cursor:pointer; padding:12px 6px; font-size:13px; }}
details.rec > summary::-webkit-details-marker {{ display:none; }}
.cell-name {{ display:flex; gap:10px; align-items:center; min-width:0; }}
.rec-more {{ color:#2b6cb0; font-weight:700; font-size:12px; text-align:right; }}
details.rec[open] .rec-more {{ color:#2a9d8f; }}
.rec-detail {{ background:#f8fafc; border-radius:10px; padding:14px; margin:0 6px 12px; display:flex;
  gap:14px; font-size:12px; color:#4a5568; line-height:1.8; }}

/* Match cards */
.m-top {{ display:flex; gap:16px; align-items:stretch; }}
.m-link {{ color:#718096; font-size:20px; align-self:center; }}
.m-bottom {{ display:flex; margin-top:16px; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden; }}

/* ---------- PHONE ---------- */
@media (max-width: 700px) {{
  /* App-owned menu: works even when Streamlit changes its sidebar-toggle DOM. */
  .st-key-mobile_nav {{ display:block !important; position:fixed; top:8px; left:8px; z-index:100002; }}
  .st-key-mobile_nav button {{ min-width:44px; min-height:44px; border-radius:8px;
    background:#0d2847 !important; color:#fff !important; border:1px solid #2a9d8f !important; }}
  /* Keep Streamlit's collapsed-sidebar control above the app's custom chrome. */
  header[data-testid="stHeader"] {{ height:3.5rem; position:fixed; inset:0 0 auto 0; z-index:100000; pointer-events:none; }}
  header[data-testid="stHeader"] button,
  [data-testid="stSidebarCollapsedControl"] {{ display:flex !important; visibility:visible !important; opacity:1 !important;
    pointer-events:auto; position:fixed; top:8px; left:8px; z-index:100001; min-width:44px; min-height:44px;
    border-radius:8px; background:#0d2847 !important; color:#fff !important; }}
  header[data-testid="stHeader"] button svg,
  [data-testid="stSidebarCollapsedControl"] svg {{ fill:#fff !important; color:#fff !important; }}
  .top-header {{ padding:0 14px 0 56px; margin-bottom:16px; }}
  .top-header .user-name {{ display:none; }}
  .st-key-body_pad {{ padding:0 14px !important; }}
  .st-key-hero {{ padding:22px 18px; border-radius:14px; }}
  .hero-title {{ font-size:30px; }}
  .page-title {{ font-size:24px; }}
  div[class*="st-key-card_"] {{ padding:14px; }}
  .m-top {{ flex-direction:column; align-items:stretch; gap:8px; }}
  .m-link {{ text-align:center; transform:rotate(90deg); align-self:center; }}
  .m-bottom {{ flex-direction:column; }}
  .score-panel {{ width:100% !important; box-sizing:border-box; }}
  .lbl {{ display:inline; }}
  .rec-head {{ display:none; }}
  details.rec {{ border:1px solid #e2e8f0; border-radius:12px; margin-bottom:10px; background:#fff; }}
  .rec-summary {{ grid-template-columns:1fr 1fr; gap:6px 10px; }}
  .rec-summary > .cell-name {{ grid-column:1 / -1; }}
  .rec-more {{ text-align:left; }}
  .rec-detail {{ flex-direction:column; margin:0 8px 10px; }}
  .stButton > button {{ min-height:44px; }}
  /* Admin rows become cards */
  div[class*="st-key-th_"] {{ display:none; }}
  div[class*="st-key-row_"] {{ border:1px solid #e2e8f0; border-radius:10px; padding:10px; margin-bottom:10px; background:#fbfcfe; }}
  div[class*="st-key-row_"] [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap; gap:6px; }}
  div[class*="st-key-row_"] [data-testid="stColumn"], div[class*="st-key-row_"] [data-testid="column"] {{
    min-width:calc(50% - 6px) !important; flex:1 1 calc(50% - 6px) !important; width:auto !important; }}
  div[class*="st-key-row_"] [data-testid="stColumn"]:first-child, div[class*="st-key-row_"] [data-testid="column"]:first-child {{
    min-width:100% !important; }}
}}
.st-key-mobile_nav {{ display:none; }}
</style>
""", unsafe_allow_html=True)

theme_css = ""
if st.session_state.ui_theme == "dark":
    theme_css = """
    .stApp { background:var(--sf-bg) !important; color:var(--sf-text) !important; }
    .stApp div[class*="st-key-card_"], .stApp .how-card,
    .stApp [data-testid="stDialog"] div[role="dialog"],
    .stApp [data-testid="stExpander"], .stApp details.rec {
      background:var(--sf-surface) !important; border-color:var(--sf-border) !important; color:var(--sf-text) !important;
    }
    .stApp .top-header { background:#101e31 !important; border-color:#34485f !important; }
    .stApp .breadcrumb, .stApp .page-sub, .stApp .rec-detail,
    .stApp [data-testid="stCaptionContainer"], .stApp .th, .stApp .rid {
      color:var(--sf-muted) !important;
    }
    .stApp .breadcrumb strong, .stApp .page-title, .stApp .cell-name,
    .stApp [data-testid="stWidgetLabel"], .stApp [data-testid="stWidgetLabel"] p,
    .stApp [data-testid="stMarkdownContainer"], .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] li, .stApp [data-testid="stRadio"] label,
    .stApp [data-testid="stRadio"] label p { color:#e8f0f8 !important; }
    .stApp [data-testid="stTextInputRootElement"], .stApp [data-testid="stTextAreaRootElement"],
    .stApp [data-testid="stDateInput"] [role="group"], .stApp [data-testid="stSelectbox"] [role="group"] {
      background:#0d1b2c !important; border-color:#53677e !important;
    }
    .stApp [data-testid="stTextInput"] input, .stApp [data-testid="stTextArea"] textarea,
    .stApp [data-testid="stDateInput"] input, .stApp [data-testid="stDateInput"] [role="spinbutton"],
    .stApp [data-testid="stSelectbox"] [role="group"] * {
      color:#f3f7fb !important; background-color:transparent !important;
    }
    .stApp [data-testid="stTextInput"] input::placeholder,
    .stApp [data-testid="stTextArea"] textarea::placeholder { color:#aebdd0 !important; }
    .stApp [data-baseweb="popover"] [role="listbox"],
    .stApp [data-baseweb="popover"] [role="option"] {
      background:var(--sf-surface) !important; color:var(--sf-text) !important;
    }
    .stApp [data-baseweb="popover"] [role="option"]:hover { background:#203b50 !important; }
    .stApp .rec-detail { background:#0d1b2c !important; }
    .stApp .pill-lost { background:#3d2a17 !important; color:#ffd08c !important; border-color:#80551e !important; }
    .stApp .pill-found { background:#123528 !important; color:#9ce3b9 !important; border-color:#28734e !important; }
    .stApp .pill-open { background:#29384a !important; color:#d5e0eb !important; }
    .stApp .notif-bar { background:#102f45 !important; border-color:#275c78 !important; color:#c6eaff !important; }
    .stApp .warn-bar, .stApp [data-testid="stAlert"] {
      background:#3b2b15 !important; border-color:#795c28 !important; color:#ffe3a9 !important;
    }
    .stApp [data-testid="stAlert"] [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stAlert"] [data-testid="stMarkdownContainer"] li { color:#ffe3a9 !important; }
    .stApp .stat-icon { background:#153b3e !important; color:#baf3e7 !important; }
    .stApp .rec-more { color:#8cc9ff !important; }
    .stApp div[class*="st-key-card_"] [style*="background:#fff"],
    .stApp div[class*="st-key-card_"] [style*="background: #fff"] {
      background:#142338 !important;
    }
    .stApp [style*="color:#1a202c"], .stApp [style*="color: #1a202c"],
    .stApp [style*="color:#0d2847"], .stApp [style*="color: #0d2847"],
    .stApp [style*="color:#4a5568"], .stApp [style*="color: #4a5568"],
    .stApp [style*="color:#718096"], .stApp [style*="color: #718096"] {
      color:#d5e0eb !important;
    }
    .stApp .stButton > button:not([kind="primary"]),
    .stApp [data-testid="stFormSubmitButton"] button:not([kind="primary"]) {
      background:#172a40 !important; border-color:#53677e !important; color:#edf4fb !important;
    }
    .stApp .stButton > button:hover { border-color:#55c7b5 !important; }
    """
else:
    theme_css = """
    .stApp { background:var(--sf-bg) !important; color:var(--sf-text) !important; }
    """

st.markdown(f"""
<style>
{theme_variables_css(st.session_state.ui_theme)}
{theme_css}
.stButton > button, [data-testid="stFormSubmitButton"] button {{
  transition: transform .2s ease, box-shadow .2s ease, background-color .2s ease, border-color .2s ease;
}}
.stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {{
  transform:translateY(-1px); box-shadow:0 5px 14px rgba(13,40,71,.12);
}}
.stButton > button:active, [data-testid="stFormSubmitButton"] button:active {{
  transform:translateY(0); box-shadow:none;
}}
div[class*="st-key-card_"] {{ animation:sf-enter .26s ease-out both; }}
div[class*="st-key-card_"], .st-key-hero, .how-card, .rec-detail {{
  overflow-wrap:anywhere; min-width:0;
}}
.page-sub {{ font-size:14px; line-height:1.55; }}
.rid, .th {{ font-size:11px; }}
button, [role="button"], summary {{ touch-action:manipulation; }}
button:focus-visible, [role="button"]:focus-visible, summary:focus-visible {{
  outline:3px solid var(--sf-accent) !important; outline-offset:3px !important;
}}
@keyframes sf-enter {{ from {{ opacity:0; transform:translateY(8px); }} to {{ opacity:1; transform:translateY(0); }} }}
@media (max-width: 900px) {{
  .st-key-body_pad {{ padding:0 20px; }}
  .rec-head, .rec-summary {{ grid-template-columns:2fr 1fr 1.4fr 1fr; }}
  .rec-summary > :nth-child(3), .rec-summary > :nth-child(5) {{ display:none; }}
}}
@media (max-width: 700px) {{
  .st-key-body_pad {{ padding:0 12px !important; }}
  .top-header {{ padding-right:12px; }}
  .st-key-body_pad [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap !important; gap:10px; }}
  .st-key-body_pad [data-testid="column"], .st-key-body_pad [data-testid="stColumn"] {{
    min-width:min(100%, 320px) !important; flex:1 1 min(100%, 320px) !important; width:auto !important;
  }}
  .rec-summary {{ grid-template-columns:1fr 1fr; }}
  .rec-summary > :nth-child(3), .rec-summary > :nth-child(5) {{ display:block; }}
  .st-key-card_admin [data-testid="stHorizontalBlock"] {{ gap:8px; }}
  .st-key-card_form [data-testid="stRadio"] [role="radiogroup"] {{ gap:8px; flex-wrap:wrap; }}
  .stApp .stButton > button, .stApp [data-testid="stFormSubmitButton"] button {{ min-height:46px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ animation-duration:.01ms !important; animation-iteration-count:1 !important;
    scroll-behavior:auto !important; transition-duration:.01ms !important; }}
}}
</style>
""", unsafe_allow_html=True)

# ============================================================
# SHARED DIALOG
# ============================================================

with st.container(key="mobile_nav"):
    with st.popover("☰ Menu"):
        st.caption("Navigate SmartFind")
        st.toggle("Dark theme", key="mobile_theme_dark",
                  on_change=update_theme_preference, args=("mobile_theme_dark",))
        for i, (name, icon) in enumerate(PAGES):
            if st.button(f"{icon}  {name}", key=f"mobile_nav_{i}", **STRETCH):
                navigate(name)
        if current_user["is_guest"] and st.session_state.get("guest_recovery_code"):
            st.caption("Save this guest recovery code privately; it is shown only once.")
            st.code(st.session_state.guest_recovery_code)
        st.button("Sign out", key="mobile_sign_out", on_click=sign_out, **STRETCH)

@st.dialog("Report details")
def show_details(rid):
    r = get_report(rid)
    if not r:
        st.write("This report no longer exists.")
        return
    html(f"""{type_pill(r)} <span class="rid" style="font-size:12px;margin-left:8px">{r['id']}</span>
    <div style="display:flex;gap:14px;margin-top:10px">{thumb(r, 88)}
    <div><div style="font-size:18px;font-weight:800">{esc(r['item'])}</div>
    <div style="font-size:13px;color:#4a5568;line-height:1.9">
    Category: <strong>{esc(r['category'])}</strong><br>Brand: <strong>{esc(r.get('brand', '')) or '—'}</strong><br>
    Color: <strong>{esc(r['color']) or '—'}</strong><br>
    Location: <strong>{esc(r['location'])}</strong><br>Date: <strong>{fmt_date(r['date'])}</strong><br>
    Status: <strong>{r['status']}</strong><br>Description: {esc(r['description']) or '—'}</div></div></div>""")


# ============================================================
# SIDEBAR + HEADER
# ============================================================

with st.sidebar:
    html("""
    <div class="logo-row"><div class="logo-icon">SF</div>
    <div><div style="color:#fff;font-size:18px;font-weight:800;line-height:1.1">SmartFind</div>
    <div style="color:#8da4be;font-size:11px">Campus Lost & Found</div></div></div>
    <div class="menu-label">MAIN MENU</div>
    """)
    for i, (name, icon) in enumerate(PAGES):
        unread_count = sum(notification["read_at"] is None for notification in st.session_state.notifications)
        label = f"{icon}   {name} ({unread_count})" if name == "Notifications" and unread_count else f"{icon}   {name}"
        if st.button(label, key=f"nav_{i}", **STRETCH):
            navigate(name)
    st.toggle("Dark theme", key="theme_dark",
              on_change=update_theme_preference, args=("theme_dark",))
    role_label = "Guest" if current_user["is_guest"] else current_user["role"].title()
    st.caption(f"{current_user['name']} · {role_label}")
    if current_user["is_guest"] and st.session_state.get("guest_recovery_code"):
        with st.expander("Save guest recovery code", expanded=True):
            st.warning("Save this code privately. It is shown only once and is required to return to this guest account.")
            st.code(st.session_state.guest_recovery_code)
            if st.button("I've saved my code", key="guest_code_saved", **STRETCH):
                st.session_state.pop("guest_recovery_code", None)
                st.rerun()

    st.button("Sign out", on_click=sign_out, **STRETCH)
    html("""
    <div style="margin-top:60px;background:rgba(255,255,255,.05);padding:10px 12px;border-radius:8px;
    border:1px solid rgba(255,255,255,.1)">
    <div style="color:#2aa99b;font-size:10px;font-weight:800">TIP CS 403 PROJECT</div>
    <div style="color:#a0aec0;font-size:10px;margin-top:2px">Perceive → Reason → Act</div></div>
    """)

html(f"""
<div class="top-header">
  <div class="breadcrumb">Campus Lost & Found &nbsp;›&nbsp; <strong>{active}</strong></div>
  <div style="display:flex;align-items:center;gap:10px">
    <div class="user-avatar">{esc(current_user['name'][:1].upper())}</div>
    <div class="user-name"><div style="color:#2d3748;font-size:12px;font-weight:700">{esc(current_user['name'])}</div>
    <div style="color:#a0aec0;font-size:10px">{role_label}</div></div>
  </div>
</div>
""")

body = st.container(key="body_pad")

with body:
    # Personal inbox summary; full notification history is on the Notifications page.
    if st.session_state.notifications and active in ("Home", "Possible Matches"):
        unread = [notification for notification in st.session_state.notifications
                  if notification["read_at"] is None]
        if unread:
            n = unread[0]
            html(f"""<div class="notif-bar"><strong>New possible match:</strong>
            \"{esc(n['item'])}\" (similarity score {n['score']}/100). View it in Notifications or Possible Matches.</div>""")

    # ========================================================
    # HOME
    # ========================================================
    if active == "Home":
        with st.container(key="hero"):
            left, right = st.columns([1.3, 1], gap="large")
            with left:
                html("""
                <div class="hero-badge">CS 403 • INTELLIGENT AGENTS PROJECT</div>
                <div class="hero-title">Find it. Report it.<br><span>Get it back.</span></div>
                <div class="hero-desc">Report a lost or found item in a few taps. SmartFind compares new
                reports against existing ones and flags possible matches.</div>
                """)
                b1, b2, _ = st.columns([1, 1, 1])
                with b1, st.container(key="hero_lost"):
                    if st.button("Report a lost item", **STRETCH):
                        navigate("Report Lost Item")
                with b2, st.container(key="hero_found"):
                    if st.button("Report a found item", **STRETCH):
                        navigate("Report Found Item")
            with right:
                html("""
                <div class="how-card">
                  <div style="display:flex;justify-content:space-between;align-items:center;
                  border-bottom:1px solid #edf2f7;padding-bottom:10px">
                    <div style="font-size:13px;font-weight:800">How SmartFind works</div>
                    <span style="background:#e6fffa;color:#234e52;font-size:9px;font-weight:800;
                    padding:2px 8px;border-radius:6px">INTELLIGENT</span></div>
                  <div class="step"><div class="step-num">1</div><div>
                    <div style="font-size:12px;font-weight:700">Perceive</div>
                    <div style="font-size:11px;color:#718096">YOLO detects a supported item, crops it, and suggests category, pixel color, and readable text for review.</div></div></div>
                  <div class="step"><div class="step-num">2</div><div>
                    <div style="font-size:12px;font-weight:700">Reason</div>
                    <div style="font-size:11px;color:#718096">Compares category, color, brand text, location, date and description.</div></div></div>
                  <div class="step"><div class="step-num">3</div><div>
                    <div style="font-size:12px;font-weight:700">Act</div>
                    <div style="font-size:11px;color:#718096">Notifies you about strong possible matches.</div></div></div>
                </div>
                """)

        st.write("")
        st.markdown('<div class="eyebrow">MAIN MENU</div>', unsafe_allow_html=True)
        st.markdown('<div class="page-title" style="font-size:22px">What would you like to do?</div>',
                    unsafe_allow_html=True)
        cards = [
            ("ⓘ", "Report Lost Item", "Add details about an item you misplaced.", "Report Lost Item"),
            ("⌕", "Report Found Item", "Record an item found around campus.", "Report Found Item"),
            ("⛓", "View Possible Matches", "Review matches calculated from report details.", "Possible Matches"),
            ("▤", "View Lost & Found Records", "Search all submitted campus item records.", "Lost & Found Records"),
        ]
        for n_card, (col, (ic, title, sub, target)) in enumerate(zip(st.columns(4), cards)):
            with col, st.container(key=f"card_home_{n_card}"):
                html(f"""<div style="display:flex;gap:12px;min-height:84px">
                <div class="stat-icon">{ic}</div><div>
                <div style="font-size:13px;font-weight:700;color:#1a202c">{title}</div>
                <div style="font-size:11px;color:#718096;margin-top:2px">{sub}</div></div></div>""")
                if st.button("Open", key=f"open_{n_card}", **STRETCH):
                    navigate(target)

        st.write("")
        chips = "".join(
            f'<div style="background:#f7fafc;border:1px solid #e2e8f0;padding:10px 16px;border-radius:10px;'
            f'font-size:12px;font-weight:700">{v["icon"]} {k}</div>' for k, v in AI_CATEGORIES.items())
        with st.container(key="card_supported"):
            html(f"""<div class="eyebrow">PHOTO RECOGNITION · YOLO</div>
            <div style="font-size:16px;font-weight:800;color:#1a202c;margin-top:4px">{len(MODEL_CATEGORIES)} supported categories across V1 and V2</div>
            <div style="color:#718096;font-size:12px;margin:4px 0 14px">Choose your detector in the sidebar. YOLO suggests an item and bounding box. OCR reads visible text (not logos), while color is estimated from crop pixels. Confirm suggestions before saving.</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap">{chips}</div>""")

        st.write("")
        status_rows = [
            ("Photo recognition", f"{'YOLOv8 model loaded' if MODEL_CATEGORIES else 'Model unavailable — manual reports still work'}; category, crop, OCR text and color suggestions", "ok" if MODEL_CATEGORIES else "warn"),
            ("Matching agent", "Working — rule-based scoring", "ok"),
            ("Notifications", "Persistent private inbox for both owners; SMTP email when configured", "ok"),
            ("Storage", "Supabase PostgreSQL", "ok"),
            ("Admin access", "Verified OIDC login with an explicit admin email allowlist", "ok"),
        ]
        items = "".join(
            f'<div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #edf2f7;font-size:12px">'
            f'<span style="color:{"#2f855a" if s == "ok" else "#dd6b20"};font-weight:800">{"●" if s == "ok" else "◐"}</span>'
            f'<div><strong>{a}</strong><div style="color:#718096">{b}</div></div></div>' for a, b, s in status_rows)
        with st.container(key="card_status"):
            html(f"""<div class="eyebrow">PROTOTYPE STATUS</div>
            <div style="font-size:16px;font-weight:800;color:#1a202c;margin:4px 0 8px">What works today</div>{items}""")

    # ========================================================
    # REPORT LOST / FOUND  (same workflow, different wording)
    # ========================================================
    elif active in ("Report Lost Item", "Report Found Item"):
        render_report_wizard("Lost" if active == "Report Lost Item" else "Found")

    # ========================================================
    # RECORDS
    # ========================================================
    elif active == "Lost & Found Records":
        html("""<div class="eyebrow">CAMPUS RECORDS</div><div class="page-title">Lost & Found Records</div>
        <div class="page-sub">Search found reports and your own lost reports. Administrators can review all records.</div>""")

        status_options = ["All statuses"] + sorted({r["status"] for r in st.session_state.reports})
        if st.session_state.records_type_filter not in ("Lost & Found", "Lost", "Found"):
            st.session_state.records_type_filter = "Lost & Found"
        if st.session_state.records_category_filter not in ["All categories"] + ALL_CATEGORIES:
            st.session_state.records_category_filter = "All categories"
        if st.session_state.records_status_filter not in status_options:
            st.session_state.records_status_filter = "All statuses"
        with st.form("records_filter_form"):
            q = st.text_input("Search records", placeholder="Search by item name, category, brand or location…",
                              key="records_search")
            f1, f2, f3 = st.columns(3)
            type_f = f1.selectbox("Type", ["Lost & Found", "Lost", "Found"],
                                  key="records_type_filter")
            cat_f = f2.selectbox("Category", ["All categories"] + ALL_CATEGORIES,
                                 key="records_category_filter")
            stat_f = f3.selectbox("Status", status_options, key="records_status_filter")
            apply_filters = st.form_submit_button("Apply filters", type="primary")
        if apply_filters:
            persist_ui_preferences(records_search=q, records_type_filter=type_f,
                                   records_category_filter=cat_f, records_status_filter=stat_f)
        clear_col, _ = st.columns([1, 4])
        clear_col.button("Clear filters", key="clear_record_filters",
                         on_click=clear_records_filters)

        recs = list(reversed(st.session_state.reports))  # newest first
        if current_user["role"] != "admin":
            recs = [r for r in recs if r["type"] == "Found"
                or r.get("user_email", "").casefold() == current_user["email"]]
        if q:
            ql = q.lower()
            recs = [r for r in recs if ql in r["item"].lower() or ql in r["category"].lower()
                    or ql in r.get("brand", "").lower() or ql in r["location"].lower()]
        if type_f != "Lost & Found":
            recs = [r for r in recs if r["type"] == type_f]
        if cat_f != "All categories":
            recs = [r for r in recs if r["category"] == cat_f]
        if stat_f != "All statuses":
            recs = [r for r in recs if r["status"] == stat_f]

        rows_html = ""
        for r in recs:
            rows_html += f"""<details class="rec"><summary class="rec-summary">
            <div class="cell-name">{thumb(r, 44)}<div style="min-width:0"><strong>{esc(r['item'])}</strong>
            <div class="rid">{r['id']}</div></div></div>
            <div><span class="lbl">Category: </span>{esc(r['category'])}</div>
            <div><span class="lbl">Color: </span>{esc(r['color']) or '—'}</div>
            <div><span class="lbl">Location: </span>{esc(r['location'])}</div>
            <div><span class="lbl">Date: </span>{fmt_date(r['date'])}</div>
            <div>{type_pill(r)}<div class="rid">{r['status']}</div></div>
            <div class="rec-more">View details ▾</div></summary>
            <div class="rec-detail">{thumb(r, 96)}<div>
            <strong style="font-size:14px;color:#1a202c">{esc(r['item'])}</strong><br>
            Category: <strong>{esc(r['category'])}</strong> · Brand: <strong>{esc(r.get('brand', '')) or '—'}</strong> ·
            Color: <strong>{esc(r['color']) or '—'}</strong><br>
            {'Last seen' if r['type'] == 'Lost' else 'Found'} at <strong>{esc(r['location'])}</strong> on <strong>{fmt_date(r['date'])}</strong><br>
            Status: <strong>{r['status']}</strong><br>
            Description: {esc(r['description']) or '—'}</div></div></details>"""

        with st.container(key="card_records"):
            html(f"""<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <strong style="font-size:13px">Recent records</strong>
            <span class="pill pill-open">{len(recs)} reports</span></div>
            <div class="rec-head"><span class="th">ITEM NAME</span><span class="th">CATEGORY</span>
            <span class="th">COLOR</span><span class="th">LOCATION</span><span class="th">DATE</span>
            <span class="th">TYPE / STATUS</span><span></span></div>""")
            if recs:
                html(rows_html)
            else:
                st.info("No reports match your search. Try clearing the filters.")

    # ========================================================
    # POSSIBLE MATCHES
    # ========================================================
    elif active == "Possible Matches":
        html("""<div class="eyebrow">SMARTFIND MATCHING AGENT</div><div class="page-title">Possible Matches</div>
        <div class="page-sub">SmartFind compares lost and found reports automatically. The similarity score (out of 100) shows how
        alike the report details are. It is <strong>not a probability and not proof of ownership</strong>,
        and it is separate from any photo-recognition confidence.</div>""")

        pairs = current_pairs()
        if current_user["role"] != "admin":
            pairs = [pair for pair in pairs
                     if current_user["email"] in (pair[1].get("user_email", "").casefold(),
                                                   pair[2].get("user_email", "").casefold())]
        notified = {notification["pair_key"] for notification in st.session_state.notifications}

        def side(label, color, r):
            return f"""<div style="flex:1;min-width:0;background:#fff;border:1px solid #e2e8f0;border-top:3px solid {color};
            border-radius:10px;padding:16px">
            <div style="display:flex;justify-content:space-between"><span style="color:{color};font-size:10px;
            font-weight:800">{label}</span><span class="rid">{r['id']}</span></div>
            <div style="display:flex;gap:12px;margin:8px 0 10px;align-items:center">{thumb(r, 56)}
            <div style="font-size:15px;font-weight:700">{esc(r['item'])}</div></div>
            <div style="font-size:12px;color:#4a5568;line-height:1.8">Category: <strong>{esc(r['category'])}</strong><br>
            Brand: <strong>{esc(r.get('brand', '')) or '—'}</strong><br>
            Color: <strong>{esc(r['color']) or '—'}</strong><br>Location: <strong>{esc(r['location'])}</strong><br>
            Date: <strong>{fmt_date(r['date'])}</strong></div></div>"""

        ICON = {"match": ("✓", "#2f855a"), "partial": ("◐", "#dd6b20"),
                "differ": ("✗", "#c53030"), "unverified": ("?", "#a0aec0")}

        for s, lo, fo, rows in pairs:
            label = "Strong possible match" if s >= NOTIFY_THRESHOLD else "Weak possible match"
            checks = ""
            for x in rows:
                ic, col = ICON[x["state"]]
                checks += (f'<div style="display:flex;justify-content:space-between;gap:8px;padding:9px 0;'
                           f'border-bottom:1px solid #edf2f7;font-size:12px"><span><span style="color:{col};'
                           f'font-weight:800">{ic}</span>&nbsp; <strong>{x["rule"]}</strong>'
                           f'<span style="color:#718096">&nbsp;{x["detail"]}</span></span>'
                           f'<span style="color:{col};font-weight:700;white-space:nowrap">{x["result"]}</span></div>')
            notif_line = ""
            if f"{lo['id']}_{fo['id']}" in notified:
                notif_line = ('<div style="margin-top:10px;font-size:11px;color:#2a4365">'
                              'Inbox notification sent to the report owners.</div>')
            with st.container(key=f"card_match_{lo['id']}_{fo['id']}"):
                html(f"""
                <div class="m-top">
                  {side('LOST REPORT', '#2b6cb0', lo)}
                  <div class="m-link">⛓</div>
                  {side('FOUND REPORT', '#2a9d8f', fo)}
                </div>
                <div class="m-bottom">
                  <div class="score-panel" style="width:240px;background:linear-gradient(160deg,#0e2a47,#1c525f);padding:24px;color:#fff;text-align:center">
                    <div style="font-size:10px;letter-spacing:1px;opacity:.7">SIMILARITY SCORE</div>
                    <div style="margin:14px auto;width:112px;height:112px;border-radius:50%;
                    background:conic-gradient(#2aa99b {s * 3.6}deg, rgba(255,255,255,.15) 0);
                    display:flex;align-items:center;justify-content:center">
                      <div style="width:90px;height:90px;border-radius:50%;background:#10345a;display:flex;
                      align-items:center;justify-content:center;flex-direction:column;font-weight:800">
                      <span style="font-size:28px;line-height:1">{s}</span>
                      <span style="font-size:11px;opacity:.7;font-weight:600">out of 100</span></div></div>
                    <div style="font-size:15px;font-weight:700">{label}</div>
                    <div style="font-size:10px;opacity:.7;margin-top:4px">Rule-based similarity of report details. Not a probability; not proof of ownership.</div>
                  </div>
                  <div style="flex:1;padding:18px 22px;background:#fff">
                    <div style="font-size:11px;font-weight:800;color:#2a9d8f">WHY THIS WAS MATCHED</div>
                    <div style="font-size:17px;margin-bottom:6px">Comparison breakdown</div>{checks}
                    <div style="font-size:10px;color:#a0aec0;margin-top:8px">✓ matches · ◐ partly matches · ✗ differs · ? not provided, so it earns no points</div>
                  </div>
                </div>
                <div style="margin-top:12px;background:#fffaf0;border:1px solid #fbd38d;color:#9c4221;
                padding:10px 14px;border-radius:8px;font-size:12px">⚠ Possible match only. Ownership must be
                verified at the campus Lost & Found office.</div>{notif_line}
                """)
            st.write("")
        if not pairs:
            html("""<div style="background:#fff;border:1px dashed #cbd5e0;border-radius:14px;padding:32px 20px;text-align:center">
            <div style="font-size:30px">🔎</div>
            <div style="font-size:15px;font-weight:700;color:#1a202c;margin-top:6px">No possible matches yet</div>
            <div style="font-size:12px;color:#718096;margin-top:4px;line-height:1.6">SmartFind compares every new lost and
            found report against the open reports on the other side.<br>Matches will appear here as soon as one is found.</div></div>""")

    elif active == "Notifications":
        html("""<div class="eyebrow">YOUR SMARTFIND INBOX</div>
        <div class="page-title">Notifications</div>
        <div class="page-sub">Strong possible matches for your reports. Inbox notices always appear here; email delivery status is shown on each notice.</div>""")
        notifications = st.session_state.notifications
        unread_count = sum(notification["read_at"] is None for notification in notifications)
        header_left, header_right = st.columns([3, 1])
        header_left.caption(f"{len(notifications)} notifications · {unread_count} unread")
        if unread_count and header_right.button("Mark all read", **STRETCH):
            mark_all_notifications_read(current_user["email"], datetime.now().isoformat(timespec="seconds"))
            st.session_state.notifications = load_notifications(current_user["email"])
            st.rerun()
        if not notifications:
            st.info("No match notifications yet. SmartFind will add one when a strong possible match is found.")
        for notification in notifications:
            with st.container(key=f"card_notification_{notification['id']}"):
                state_label = "Unread" if notification["read_at"] is None else "Read"
                email_status = notification.get("email_status", "pending")
                if current_user["is_guest"] or email_status == "not_applicable":
                    email_label = "In-app only"
                elif email_status == "sent":
                    email_label = "Email sent"
                elif email_status == "failed":
                    email_label = "Email failed"
                elif email_status == "sending":
                    email_label = "Email sending"
                else:
                    email_label = "Email queued" if is_configured(mail_config) else "Email not configured"
                html(f"""<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">
                <div><strong>Possible match for {esc(notification['item'])}</strong>
                <div style="font-size:12px;color:#718096;margin-top:4px">Similarity {notification['score']}/100 · {esc(notification['time'])} · {state_label} · {email_label}</div></div>
                <span class="pill pill-open">{state_label}</span></div>""")
                button_cols = st.columns([1, 1, 1, 3])
                if notification["read_at"] is None and button_cols[0].button(
                        "Mark read", key=f"notif_read_{notification['id']}"):
                    mark_notification_read(notification["id"], current_user["email"],
                                           datetime.now().isoformat(timespec="seconds"))
                    st.session_state.notifications = load_notifications(current_user["email"])
                    st.rerun()
                if button_cols[1].button("View matches", key=f"notif_matches_{notification['id']}"):
                    navigate("Possible Matches")
                if email_status == "failed" and is_configured(mail_config) and button_cols[2].button(
                        "Retry email", key=f"notif_retry_{notification['id']}"):
                    if retry_notification_email(notification["id"], current_user["email"]):
                        deliver_pending_notification_emails()
                        st.session_state.notifications = load_notifications(current_user["email"])
                    st.rerun()
                if email_status == "failed":
                    if "check the inbox before retrying" in str(notification.get("email_error", "")).casefold():
                        st.warning("The previous send was interrupted. Check your inbox and spam folder before retrying to avoid a duplicate email.")
                    else:
                        st.caption("Email delivery failed. You can still review the possible match in SmartFind.")
                    if notification.get("email_error") and "check the inbox before retrying" not in str(
                            notification["email_error"]).casefold():
                        st.caption(f"SMTP diagnostic: {esc(notification['email_error'])}")
                elif email_status == "sending" and button_cols[2].button(
                        "Refresh status", key=f"notif_refresh_{notification['id']}"):
                    st.rerun()
            st.write("")

    # ========================================================
    # ADMIN
    # ========================================================
    elif active == "Admin Management":
        html("""<div class="eyebrow">RECORD ADMINISTRATION</div><div class="page-title">Lost-and-Found Management</div>
        <div class="page-sub">Review, update, resolve, or delete item reports. Changes are reflected in Records and Possible Matches.</div>""")

        html("""<div class="notif-bar"><strong>Administrator access.</strong> This page is available only to
        verified accounts listed in the app's admin email allowlist.</div>""")

        if is_configured(mail_config) and st.button("Test Gmail connection", key="test_gmail_smtp"):
            try:
                test_smtp_connection(mail_config)
            except SMTPDeliveryError as exc:
                st.error(f"SMTP connection test failed: {esc(exc)}")
            else:
                st.success("Gmail SMTP connection and login succeeded. No email was sent.")

        reps = st.session_state.reports
        stats = [("ⓘ", "Total Lost Reports", sum(r["type"] == "Lost" for r in reps)),
                 ("⌕", "Total Found Reports", sum(r["type"] == "Found" for r in reps)),
                 ("⛓", "Possible Matches", len(current_pairs())),
                 ("✓", "Resolved Items", sum(r["status"] == "Resolved" for r in reps))]
        for col, (ic, lbl, val) in zip(st.columns(4), stats):
            with col:
                html(f"""<div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px;
                display:flex;gap:14px;align-items:center;margin-bottom:8px"><div class="stat-icon">{ic}</div>
                <div><div style="font-size:11px;color:#718096">{lbl}</div>
                <div style="font-size:26px;font-weight:800;color:#0d2847">{val}</div></div></div>""")
        st.write("")

        @st.dialog("Update report")
        def update_dialog(rid):
            r = get_report(rid)
            if not r:
                return
            st.caption(f"{r['id']} — {r['item']}")
            statuses = ["Searching", "Resolved"] if r["type"] == "Lost" else ["Reported", "Resolved"]
            new_status = st.selectbox("Status", statuses,
                                      index=statuses.index(r["status"]) if r["status"] in statuses else 0)
            new_loc = st.text_input("Location", value=r["location"])
            if st.button("Save changes", **STRETCH):
                r["status"], r["location"] = new_status, new_loc.strip() or r["location"]
                save_report(r)
                auto_monitor_and_notify()
                st.rerun()

        @st.dialog("Delete report")
        def delete_dialog(rid):
            r = get_report(rid)
            if not r:
                return
            st.warning(f"Delete {r['id']} — {r['item']}? This can't be undone.")
            if st.button("Delete report", type="primary", **STRETCH):
                st.session_state.reports = [x for x in st.session_state.reports if x["id"] != rid]
                delete_report(rid)
                auto_monitor_and_notify()
                st.rerun()

        W = [2.6, 0.9, 1.3, 1.3, 0.8, 0.9, 0.9, 0.8]
        with st.container(key="card_admin"):
            st.markdown("**Recent reports**")
            with st.container(key="th_admin"):
                for col, h in zip(st.columns(W), ["ITEM", "TYPE", "DATE", "STATUS", "", "", "", ""]):
                    col.markdown(f'<span class="th">{h}</span>', unsafe_allow_html=True)
            if not reps:
                st.info("There are no reports yet.")
            for r in list(reps):
                rid = r["id"]
                with st.container(key=f"row_adm_{rid}"):
                    c = st.columns(W)
                    c[0].markdown(
                        f'<div style="display:flex;gap:10px;align-items:center">{thumb(r, 36)}<div>'
                        f'<strong>{esc(r["item"])}</strong><div class="rid">{rid}</div></div></div>',
                        unsafe_allow_html=True)
                    c[1].markdown(type_pill(r), unsafe_allow_html=True)
                    c[2].write(fmt_date(r["date"]))
                    c[3].write(r["status"])
                    if c[4].button("View", key=f"a_view_{rid}", **STRETCH):
                        show_details(rid)
                    if c[5].button("Update", key=f"a_upd_{rid}", **STRETCH):
                        update_dialog(rid)
                    if c[6].button("Resolve", key=f"a_res_{rid}", **STRETCH,
                                   disabled=r["status"] == "Resolved"):
                        r["status"] = "Resolved"
                        save_report(r)
                        auto_monitor_and_notify()
                        st.rerun()
                    if c[7].button("Delete", key=f"a_del_{rid}", **STRETCH):
                        delete_dialog(rid)
