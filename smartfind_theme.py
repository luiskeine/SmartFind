"""SmartFind's accessible color tokens and contrast helpers."""


THEME_TOKENS = {
    "light": {
        "color-scheme": "light",
        "bg": "#f4f7fb",
        "surface": "#ffffff",
        "elevated": "#f8fafc",
        "text": "#0d2847",
        "muted": "#52657a",
        "placeholder": "#52657a",
        "border": "#d5deea",
        "accent": "#0f766e",
        "primary-bg": "#0f766e",
        "primary-text": "#ffffff",
        "primary-hover": "#115e59",
        "secondary-bg": "#ffffff",
        "secondary-text": "#0d2847",
        "secondary-border": "#cbd5e0",
        "disabled-bg": "#f1f5f9",
        "disabled-text": "#52657a",
        "sidebar-bg": "#0d2847",
        "sidebar-text": "#d1e2f2",
        "sidebar-muted": "#a9bfd2",
        "sidebar-active-bg": "#14546b",
        "sidebar-active-text": "#ffffff",
        "alert-bg": "#f8fafc",
        "alert-text": "#0d2847",
        "status-lost-bg": "#fffaf0",
        "status-lost-text": "#9c4221",
        "status-found-bg": "#f0fff4",
        "status-found-text": "#276749",
        "status-open-bg": "#edf2f7",
        "status-open-text": "#4a5568",
        "notification-bg": "#ebf8ff",
        "notification-text": "#2a4365",
        "warning-bg": "#fffaf0",
        "warning-text": "#7b341e",
        "hero-bg": "#0e2a47",
        "hero-bg-mid": "#15395f",
        "hero-bg-end": "#1c525f",
        "hero-text": "#ffffff",
        "hero-muted": "#cddbe8",
        "hero-accent": "#83e3d3",
    },
    "dark": {
        "color-scheme": "dark",
        "bg": "#0b1525",
        "surface": "#142338",
        "elevated": "#1a2c42",
        "text": "#e8f0f8",
        "muted": "#b5c4d5",
        "placeholder": "#b5c4d5",
        "border": "#455b73",
        "accent": "#55c7b5",
        "primary-bg": "#55c7b5",
        "primary-text": "#0b1525",
        "primary-hover": "#72d8c8",
        "secondary-bg": "#172a40",
        "secondary-text": "#edf4fb",
        "secondary-border": "#53677e",
        "disabled-bg": "#29384a",
        "disabled-text": "#b5c4d5",
        "sidebar-bg": "#0d2847",
        "sidebar-text": "#d1e2f2",
        "sidebar-muted": "#a9bfd2",
        "sidebar-active-bg": "#14546b",
        "sidebar-active-text": "#ffffff",
        "alert-bg": "#1a2c42",
        "alert-text": "#e8f0f8",
        "status-lost-bg": "#3d2a17",
        "status-lost-text": "#ffd08c",
        "status-found-bg": "#123528",
        "status-found-text": "#9ce3b9",
        "status-open-bg": "#29384a",
        "status-open-text": "#d5e0eb",
        "notification-bg": "#102f45",
        "notification-text": "#c6eaff",
        "warning-bg": "#3b2b15",
        "warning-text": "#ffe3a9",
        "hero-bg": "#0e2a47",
        "hero-bg-mid": "#15395f",
        "hero-bg-end": "#1c525f",
        "hero-text": "#ffffff",
        "hero-muted": "#cddbe8",
        "hero-accent": "#83e3d3",
    },
}


CONTRAST_PAIRS = (
    ("text", "bg"),
    ("text", "surface"),
    ("text", "elevated"),
    ("muted", "bg"),
    ("muted", "surface"),
    ("placeholder", "surface"),
    ("accent", "surface"),
    ("muted", "elevated"),
    ("primary-bg", "surface"),
    ("primary-bg", "elevated"),
    ("primary-text", "primary-bg"),
    ("secondary-text", "secondary-bg"),
    ("disabled-text", "disabled-bg"),
    ("sidebar-text", "sidebar-bg"),
    ("sidebar-muted", "sidebar-bg"),
    ("sidebar-active-text", "sidebar-active-bg"),
    ("alert-text", "alert-bg"),
    ("status-lost-text", "status-lost-bg"),
    ("status-found-text", "status-found-bg"),
    ("status-open-text", "status-open-bg"),
    ("notification-text", "notification-bg"),
    ("warning-text", "warning-bg"),
    ("hero-text", "hero-bg"),
    ("hero-text", "hero-bg-mid"),
    ("hero-text", "hero-bg-end"),
    ("hero-muted", "hero-bg"),
    ("hero-muted", "hero-bg-mid"),
    ("hero-muted", "hero-bg-end"),
    ("hero-accent", "hero-bg"),
    ("hero-accent", "hero-bg-mid"),
    ("hero-accent", "hero-bg-end"),
)


def theme_variables_css(theme):
    """Return CSS variables for a supported theme, defaulting to light."""
    tokens = THEME_TOKENS.get(theme, THEME_TOKENS["light"])
    variables = [f"--sf-{name}:{value}" for name, value in tokens.items()
                 if name != "color-scheme"]
    return (f":root {{ color-scheme:{tokens['color-scheme']}; "
            f"{'; '.join(variables)}; }}")


def theme_stylesheet(theme, active_nav_index=None):
    """Return shared theme rules for authentication and app controls."""
    variables = theme_variables_css(theme)
    active_nav_rule = ""
    if active_nav_index is not None:
        active_nav_rule = f"""
        .stApp section[data-testid="stSidebar"] .st-key-nav_{active_nav_index}
        button[data-testid="stBaseButton-secondary"] {{
          background:var(--sf-sidebar-active-bg) !important;
          color:var(--sf-sidebar-active-text) !important;
          border-color:var(--sf-accent) !important;
        }}
        .stApp section[data-testid="stSidebar"] .st-key-nav_{active_nav_index}
        button[data-testid="stBaseButton-secondary"] * {{
          color:var(--sf-sidebar-active-text) !important;
        }}
        """

    return f"""<style>
    {variables}
    .stApp {{
      color-scheme:{THEME_TOKENS.get(theme, THEME_TOKENS["light"])["color-scheme"]};
      background:var(--sf-bg) !important; color:var(--sf-text) !important;
    }}
    .stApp [data-testid="stMarkdownContainer"],
    .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] li,
    .stApp [data-testid="stWidgetLabel"],
    .stApp [data-testid="stWidgetLabel"] *,
    .stApp [data-testid="stRadio"] label,
    .stApp [data-testid="stRadio"] label *,
    .stApp [data-testid="stCaptionContainer"],
    .stApp [data-testid="stCaptionContainer"] *,
    .stApp .page-title,
    .stApp .breadcrumb strong,
    .stApp .cell-name {{ color:var(--sf-text) !important; }}
    .stApp [data-testid="stCaptionContainer"],
    .stApp [data-testid="stCaptionContainer"] *,
    .stApp .page-sub,
    .stApp .breadcrumb,
    .stApp .rec-detail,
    .stApp .th,
    .stApp .rid,
    .stApp .lbl {{ color:var(--sf-muted) !important; }}

    .stApp [data-testid="stTextInputRootElement"],
    .stApp [data-testid="stTextAreaRootElement"],
    .stApp [data-testid="stDateInput"] [role="group"],
    .stApp [data-testid="stSelectbox"] [role="group"] {{
      background:var(--sf-surface) !important;
      border:1px solid var(--sf-border) !important;
      color:var(--sf-text) !important;
    }}
    .stApp [data-testid="stTextInput"] input,
    .stApp [data-testid="stTextArea"] textarea,
    .stApp [data-testid="stDateInput"] input,
    .stApp [data-testid="stDateInput"] [role="spinbutton"],
    .stApp [data-testid="stSelectbox"] [role="group"] *,
    .stApp [data-testid="stMultiSelect"] [role="group"] * {{
      background-color:transparent !important;
      color:var(--sf-text) !important;
      caret-color:var(--sf-accent) !important;
    }}
    .stApp [data-testid="stTextInput"] input::placeholder,
    .stApp [data-testid="stTextArea"] textarea::placeholder,
    .stApp [data-testid="stDateInput"] input::placeholder {{
      color:var(--sf-placeholder) !important; opacity:1 !important;
    }}
    .stApp [data-testid="stTextInputRootElement"] button {{
      background:transparent !important; color:var(--sf-muted) !important;
      border:0 !important; box-shadow:none !important;
    }}
    .stApp [data-testid="stTextInputRootElement"] button *,
    .stApp [data-testid="stTextInputRootElement"] button svg {{
      color:var(--sf-muted) !important; fill:var(--sf-muted) !important;
    }}
    .stApp [data-baseweb="popover"] [role="listbox"],
    .stApp [data-baseweb="popover"] [role="option"] {{
      background:var(--sf-surface) !important; color:var(--sf-text) !important;
    }}
    .stApp [data-baseweb="popover"] [role="option"]:hover {{
      background:var(--sf-elevated) !important;
    }}
    .stApp [data-testid="stTextInputRootElement"]:focus-within,
    .stApp [data-testid="stTextAreaRootElement"]:focus-within,
    .stApp [data-testid="stDateInput"] [role="group"]:focus-within,
    .stApp [data-testid="stSelectbox"] [role="group"]:focus-within {{
      border-color:var(--sf-accent) !important;
      box-shadow:0 0 0 1px var(--sf-accent) !important;
    }}

    .stApp [data-testid="stFileUploaderDropzone"] {{
      background:var(--sf-elevated) !important;
      border:1px solid var(--sf-border) !important;
      color:var(--sf-text) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzoneInstructions"],
    .stApp [data-testid="stFileUploaderDropzoneInstructions"] * {{
      color:var(--sf-muted) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzone"] [data-testid="stIconMaterial"] {{
      color:var(--sf-accent) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] {{
      background:var(--sf-secondary-bg) !important;
      color:var(--sf-secondary-text) !important;
      border:1px solid var(--sf-secondary-border) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] *,
    .stApp [data-testid="stFileUploaderDropzone"] button[data-testid="stBaseButton-secondary"] [data-testid="stIconMaterial"] {{
      color:var(--sf-secondary-text) !important;
      fill:var(--sf-secondary-text) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzone"]:hover,
    .stApp [data-testid="stFileUploaderDropzone"]:focus-within {{
      border-color:var(--sf-accent) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzone"]:focus-within {{
      box-shadow:0 0 0 2px var(--sf-accent) !important;
    }}
    .stApp [data-testid="stFileUploaderDropzone"] button:focus-visible {{
      outline:3px solid var(--sf-accent) !important;
      outline-offset:2px !important;
    }}

    .stApp [data-testid="stRadioOption"] > div > div:first-child {{
      background:var(--sf-surface) !important;
      border:1px solid var(--sf-border) !important;
    }}
    .stApp [data-testid="stRadioOption"][data-selected="true"] > div > div:first-child {{
      background:var(--sf-primary-bg) !important;
      border-color:var(--sf-primary-bg) !important;
    }}
    .stApp [data-testid="stRadioOption"] > div > div:first-child > div {{
      background:var(--sf-surface) !important;
    }}
    .stApp [data-testid="stRadioOption"]:hover > div > div:first-child {{
      border-color:var(--sf-accent) !important;
    }}

    .stApp [data-testid="stProgressBarTrack"] {{
      background:var(--sf-elevated) !important;
    }}
    .stApp [data-testid="stProgressBarTrack"] > div {{
      background:var(--sf-primary-bg) !important;
    }}
    .stApp [data-testid="stExpander"] summary {{
      background:var(--sf-surface) !important;
      color:var(--sf-text) !important;
    }}
    .stApp [data-testid="stExpander"] summary:hover {{
      background:var(--sf-elevated) !important;
    }}
    .stApp [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{
      color:var(--sf-muted) !important;
    }}

    .stApp .stButton > button,
    .stApp [data-testid="stFormSubmitButton"] button {{
      min-height:44px; border-radius:10px;
      transition:transform .18s ease, box-shadow .18s ease, background-color .18s ease;
    }}
    .stApp .stButton > button[data-testid^="stBaseButton-primary"],
    .stApp .stButton > button[kind="primary"],
    .stApp [data-testid="stFormSubmitButton"] button[kind="primary"],
    .stApp [data-testid="stFormSubmitButton"] button[data-testid^="stBaseButton-primary"] {{
      background:var(--sf-primary-bg) !important;
      color:var(--sf-primary-text) !important;
      border:1px solid var(--sf-primary-bg) !important;
    }}
    .stApp .stButton > button[data-testid^="stBaseButton-primary"] *,
    .stApp .stButton > button[kind="primary"] *,
    .stApp [data-testid="stFormSubmitButton"] button[kind="primary"] *,
    .stApp [data-testid="stFormSubmitButton"] button[data-testid^="stBaseButton-primary"] * {{
      color:var(--sf-primary-text) !important;
    }}
    .stApp .stButton > button[data-testid^="stBaseButton-primary"]:hover,
    .stApp .stButton > button[kind="primary"]:hover,
    .stApp [data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
    .stApp [data-testid="stFormSubmitButton"] button[data-testid^="stBaseButton-primary"]:hover {{
      background:var(--sf-primary-hover) !important; border-color:var(--sf-primary-hover) !important;
    }}
    .stApp .stButton > button:not([data-testid^="stBaseButton-primary"]):not([kind="primary"]),
    .stApp [data-testid="stFormSubmitButton"] button:not([data-testid^="stBaseButton-primary"]):not([kind="primary"]) {{
      background:var(--sf-secondary-bg) !important;
      color:var(--sf-secondary-text) !important;
      border-color:var(--sf-secondary-border) !important;
    }}
    .stApp .stButton > button:not([data-testid^="stBaseButton-primary"]):not([kind="primary"]) *,
    .stApp [data-testid="stFormSubmitButton"] button:not([data-testid^="stBaseButton-primary"]):not([kind="primary"]) * {{
      color:var(--sf-secondary-text) !important;
    }}
    .stApp .stButton > button:disabled,
    .stApp [data-testid="stFormSubmitButton"] button:disabled {{
      background:var(--sf-disabled-bg) !important;
      color:var(--sf-disabled-text) !important;
      border-color:var(--sf-border) !important;
      opacity:1 !important;
    }}
    .stApp .stButton > button:disabled *,
    .stApp [data-testid="stFormSubmitButton"] button:disabled * {{
      color:var(--sf-disabled-text) !important;
    }}

    .stApp section[data-testid="stSidebar"],
    .stApp section[data-testid="stSidebar"] > div {{
      background:var(--sf-sidebar-bg) !important;
    }}
    .stApp section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"],
    .stApp section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"] * {{
      background:transparent !important; color:var(--sf-sidebar-text) !important;
      border-color:transparent !important; box-shadow:none !important;
    }}
    .stApp section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"]:hover {{
      background:rgba(255,255,255,.10) !important;
    }}
    .stApp section[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"]:hover * {{
      color:#ffffff !important;
    }}
    .stApp section[data-testid="stSidebar"] .menu-label {{
      color:var(--sf-sidebar-muted) !important;
    }}
    {active_nav_rule}

    .stApp div[class*="st-key-card_"],
    .stApp .how-card,
    .stApp [data-testid="stDialog"] div[role="dialog"],
    .stApp [data-testid="stExpander"],
    .stApp details.rec {{
      background:var(--sf-surface) !important;
      border-color:var(--sf-border) !important;
      color:var(--sf-text) !important;
    }}
    .stApp [data-testid="stDialog"] div[role="dialog"] button[aria-label="Close"] {{
      color:var(--sf-muted) !important;
    }}
    .stApp [data-testid="stExpander"] summary,
    .stApp [data-testid="stExpander"] summary *,
    .stApp [data-testid="stExpander"] summary svg {{
      color:var(--sf-text) !important; fill:var(--sf-text) !important;
    }}
    .stApp .top-header {{ background:var(--sf-surface) !important; border-color:var(--sf-border) !important; }}
    .stApp .rec-detail {{ background:var(--sf-elevated) !important; }}
    .stApp .pill-lost {{
      background:var(--sf-status-lost-bg) !important; color:var(--sf-status-lost-text) !important;
    }}
    .stApp .pill-found {{
      background:var(--sf-status-found-bg) !important; color:var(--sf-status-found-text) !important;
    }}
    .stApp .pill-open {{
      background:var(--sf-status-open-bg) !important; color:var(--sf-status-open-text) !important;
    }}
    .stApp .notif-bar {{
      background:var(--sf-notification-bg) !important;
      border-color:var(--sf-border) !important; color:var(--sf-notification-text) !important;
    }}
    .stApp .warn-bar {{
      background:var(--sf-warning-bg) !important;
      border-color:var(--sf-border) !important; color:var(--sf-warning-text) !important;
    }}
    .stApp [data-testid="stAlert"] {{
      background:var(--sf-alert-bg) !important;
      border-color:var(--sf-border) !important; color:var(--sf-alert-text) !important;
    }}
    .stApp [data-testid="stAlert"] *,
    .stApp [data-testid="stAlert"] [data-testid="stMarkdownContainer"] * {{
      color:var(--sf-alert-text) !important;
    }}
    .stApp .stat-icon {{ background:var(--sf-elevated) !important; color:var(--sf-accent) !important; }}
    .stApp .rec-more {{ color:var(--sf-accent) !important; }}
    .stApp .st-key-hero_lost .stButton > button {{
      background:var(--sf-primary-bg) !important; color:var(--sf-primary-text) !important;
      border-color:var(--sf-primary-bg) !important;
    }}
    .stApp .st-key-hero_lost .stButton > button * {{ color:var(--sf-primary-text) !important; }}
    .stApp .st-key-hero_found .stButton > button {{
      background:transparent !important; color:var(--sf-hero-text) !important;
      border-color:rgba(255,255,255,.55) !important;
    }}
    .stApp .st-key-hero_found .stButton > button * {{ color:var(--sf-hero-text) !important; }}
    .stApp .hero-title span {{ color:var(--sf-hero-accent) !important; }}
    .stApp .hero-desc {{ color:var(--sf-hero-muted) !important; }}

    .stApp [data-testid="stMarkdownContainer"] [style*="color:#0d2847"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color: #0d2847"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color:#1a202c"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color: #1a202c"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color:#2d3748"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color:#4a5568"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color: #4a5568"] {{
      color:var(--sf-text) !important;
    }}
    .stApp [data-testid="stMarkdownContainer"] [style*="color:#718096"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color: #718096"],
    .stApp [data-testid="stMarkdownContainer"] [style*="color:#a0aec0"] {{
      color:var(--sf-muted) !important;
    }}
    .stApp [data-testid="stMarkdownContainer"] [style*="background:#fff"],
    .stApp [data-testid="stMarkdownContainer"] [style*="background: #fff"],
    .stApp [data-testid="stMarkdownContainer"] [style*="background:#ffffff"] {{
      background:var(--sf-surface) !important;
    }}
    :focus-visible {{ outline:3px solid var(--sf-accent) !important; outline-offset:3px !important; }}
    @media (prefers-reduced-motion: reduce) {{
      *, *::before, *::after {{
        animation-duration:.01ms !important; animation-iteration-count:1 !important;
        scroll-behavior:auto !important; transition-duration:.01ms !important;
      }}
    }}
    </style>"""


def contrast_ratio(foreground, background):
    """Calculate WCAG relative luminance contrast for two hex colors."""
    def luminance(color):
        if len(color) == 4:
            color = "#" + "".join(channel * 2 for channel in color[1:])
        rgb = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
        linear = tuple(value / 12.92 if value <= 0.04045
                       else ((value + 0.055) / 1.055) ** 2.4 for value in rgb)
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
