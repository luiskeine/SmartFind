"""SmartFind's accessible color tokens and contrast helpers."""


THEME_TOKENS = {
    "light": {
        "color-scheme": "light",
        "bg": "#f4f7fb",
        "surface": "#ffffff",
        "elevated": "#f8fafc",
        "text": "#0d2847",
        "muted": "#52657a",
        "border": "#d5deea",
        "accent": "#0f766e",
    },
    "dark": {
        "color-scheme": "dark",
        "bg": "#0b1525",
        "surface": "#142338",
        "elevated": "#1a2c42",
        "text": "#e8f0f8",
        "muted": "#b5c4d5",
        "border": "#34485f",
        "accent": "#55c7b5",
    },
}


def theme_variables_css(theme):
    """Return CSS variables for a supported theme, defaulting to light."""
    tokens = THEME_TOKENS.get(theme, THEME_TOKENS["light"])
    variables = [f"--sf-{name}:{value}" for name, value in tokens.items()
                 if name != "color-scheme"]
    return f":root {{ color-scheme:{tokens['color-scheme']}; {'; '.join(variables)}; }}"


def contrast_ratio(foreground, background):
    """Calculate WCAG relative luminance contrast for two hex colors."""
    def luminance(color):
        rgb = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
        linear = tuple(value / 12.92 if value <= 0.04045
                       else ((value + 0.055) / 1.055) ** 2.4 for value in rgb)
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)
