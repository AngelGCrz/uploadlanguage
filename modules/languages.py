"""Supported languages: DOCX filename prefixes, language codes and exclusions."""
from __future__ import annotations

PREFIXES = {
    "GER": "deu", "GRE": "ell", "FRE": "fra", "IND": "ido", "ITA": "ita",
    "JAP": "jpn", "CAM": "kmb", "SOU": "krs", "MAL": "mly", "POR": "por",
    "RUS": "rus", "THA": "tha", "TUR": "tur", "VIE": "vie",
}
EXCLUDED = {"eng", "esp", "zh-hant", "zh-hans"}


def language_prefixes(config):
    """Prefix -> language mapping from config.json, limited to the supported languages."""
    prefixes = config.get("prefixes", PREFIXES)
    for prefix, lang in prefixes.items():
        if len(prefix) != 3 or prefix != prefix.upper() or lang not in PREFIXES.values():
            raise ValueError(f"Prefijo/idioma no permitido: {prefix} -> {lang}")
    return prefixes


def language_for(path, prefixes):
    """Language of a DOCX from the first three characters of its name, or None."""
    return prefixes.get(path.stem.lstrip()[:3].upper())


def requested_languages(value):
    """Parse --lang (comma separated) and reject excluded or unknown languages."""
    if not value:
        return None
    requested = list(dict.fromkeys(lang.strip() for lang in value.split(",")))
    if set(requested) & EXCLUDED or set(requested) - set(PREFIXES.values()):
        raise ValueError("Solo se admiten los 14 idiomas individuales; inglés, español y ambos chinos están excluidos")
    return requested
