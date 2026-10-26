"""Text normalisation, marker (token) conversion and line wrapping."""
from __future__ import annotations

import functools
import re
import unicodedata

TOKEN = re.compile(r"##[^#]+##|\[[^\[\]]+\]")
CONDITION = re.compile(r"^\s*\{fixedJackpot\}")
BULLET = re.compile(r"^\s*(?:\{fixedJackpot\})?\s*[•●]")


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def identity(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    numeric_marks = {".": "decimalpoint", ",": "numericcomma", "/": "ratio", "-": "range",
                     "+": "plus", "×": "multiply"}
    text = re.sub(r"(?<=\d)[.,/\-+×](?=\d)", lambda match: numeric_marks[match.group()], text)
    text = re.sub(r"(?<!\w)-(?=\d)", "negative", text)
    return re.sub(r"[\W_]+", "", text)


def header(text):
    return "".join(c for c in unicodedata.normalize("NFKD", clean(text))
                   if not unicodedata.combining(c)).upper()

def strip_rule(text):
    text = CONDITION.sub("", text)
    return re.sub(r"^\s*[•●]\s*", "", text).strip()


def asset_name(label, config):
    label = label.strip().upper()
    symbol = re.fullmatch(r"(?:SYMBOLS?|SYM)_(\d+)([A-Z]*)", label)
    return config.get("tokens", {}).get(label) or (
        f"sym_{int(symbol[1])}{symbol[2].lower()}.png" if symbol else None)


def direct_tokens(text, english, allowed, config):
    """Convert [MARKER] to ##asset## without comparing with the template's English text.

    Bracket typos and mistyped/translated names (SIMBOL_8A, ÍCONE_GRAND_JACKPOT) are resolved
    against the template images and the markers of the same DOCX row.
    Returns (text, unresolved markers, repaired)."""
    template_assets = {token_label(re.sub(r"\.[^.]+$", "", asset)): asset for asset in allowed}

    def resolve(label):
        return (asset_name(label, config) or asset_name(token_label(label), config)
                or similar_label(token_label(label), template_assets))

    row_assets = {}
    for raw in TOKEN.findall(english or ""):
        if raw.startswith("["):
            asset = resolve(raw[1:-1])
            if asset:
                row_assets[token_label(raw[1:-1])] = asset
    unresolved, repaired = [], False

    def convert(match):
        nonlocal repaired
        raw = match.group()
        if raw.startswith("##"):
            return raw
        label = raw[1:-1]
        asset = asset_name(label, config) or asset_name(token_label(label), config)
        if not asset:
            asset = similar_label(token_label(label), template_assets) or similar_label(token_label(label), row_assets)
            repaired = repaired or asset is not None
        if not asset:
            unresolved.append(raw)
            return raw
        return f"##{asset}##"

    fixed = repair_markers(text, english or "")
    converted = TOKEN.sub(convert, fixed)
    return converted, unresolved, repaired or fixed != text


def token_label(label):
    label = "".join(c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c))
    return re.sub(r"\s+", "", label).upper().removesuffix("_ICON")


def label_digits(label):
    """Numeric identity of a marker: SYMBOL_17A, SIMBOL_17A and SÍMBOLO_17A all give 17A."""
    match = re.search(r"(\d+)([A-Z]?)$", token_label(label).rstrip("_"))
    return f"{int(match[1])}{match[2]}" if match else None


def label_words(label):
    ignored = {"ICON", "ICONE", "ICONO", "ICONA", "IKON", "SYMBOL", "SYMBOLS", "NAME"}
    return {word for word in re.split(r"[^A-Z0-9]+", token_label(label))
            if len(word) >= 3 and not word.isdigit() and word not in ignored}


def similar_label(label, candidates):
    """Resolve a mistyped/translated marker against the markers of the same English row."""
    if label in candidates:
        return candidates[label]
    digits = label_digits(label)
    if digits:
        assets = {asset for name, asset in candidates.items() if label_digits(name) == digits}
    else:
        words = label_words(label)
        assets = {asset for name, asset in candidates.items() if words & label_words(name)}
    return assets.pop() if len(assets) == 1 else None


def repair_markers(text, source):
    """Fix bracket typos ([[X]], X], [X) for markers that exist in the English source row."""
    text = re.sub(r"\[+\s*", "[", text)
    text = re.sub(r"\s*\]+", "]", text)
    labels = sorted({raw[1:-1].strip() for raw in TOKEN.findall(source) if raw.startswith("[")}, key=len, reverse=True)
    for label in labels:
        name = re.escape(label)
        text = re.sub(rf"(?<![\[\w]){name}\]", f"[{label}]", text, flags=re.IGNORECASE)
        text = re.sub(rf"\[{name}(?![\w\]])", f"[{label}]", text, flags=re.IGNORECASE)
    return text


def positional_token_mapping(source, expected):
    source_tokens, expected_tokens = TOKEN.findall(source), TOKEN.findall(expected)
    if len(source_tokens) != len(expected_tokens):
        return {}
    mapping = {}
    for raw, reference in zip(source_tokens, expected_tokens):
        if not raw.startswith("[") or not reference.startswith("##"):
            continue
        label, asset = token_label(raw[1:-1]), reference[2:-2]
        if label in mapping and mapping[label] != asset:
            return {}
        mapping[label] = asset
    return mapping


def convert_tokens(text, allowed, config, inferred=None, fuzzy=None):
    def convert(match):
        raw = match.group()
        if raw.startswith("##"):
            asset = raw[2:-2]
        else:
            label = token_label(raw[1:-1])
            asset = ((inferred or {}).get(label) or (inferred or {}).get(raw[1:-1].strip().upper()) or
                     (similar_label(label, fuzzy) if fuzzy else None) or asset_name(raw[1:-1], config))
        if asset not in allowed:
            raise ValueError(f"Símbolo sin correspondencia inglesa: {raw}")
        return f"##{asset}##"
    converted = TOKEN.sub(convert, text)
    if any(char in converted for char in "[]"):
        raise ValueError("Marcador incompleto")
    return converted


def source_match(source, expected, allowed, config, known_labels=None):
    source, expected = strip_rule(source), strip_rule(expected)
    try:
        return (identity(convert_tokens(source, allowed, config, known_labels)) == identity(expected), {})
    except ValueError:
        # Infer a named marker only when the English sentence and asset positions agree.
        if identity(TOKEN.sub("ASSET", source)) != identity(TOKEN.sub("ASSET", expected)):
            return False, {}
        source_tokens, expected_tokens = TOKEN.findall(source), TOKEN.findall(expected)
        if len(source_tokens) != len(expected_tokens):
            return False, {}
        inferred = {}
        for raw, reference in zip(source_tokens, expected_tokens):
            if not reference.startswith("##"):
                return False, {}
            asset = reference[2:-2]
            known = raw[2:-2] if raw.startswith("##") else (
                (known_labels or {}).get(token_label(raw[1:-1])) or asset_name(raw[1:-1], config))
            if known and known != asset:
                return False, {}
            if raw.startswith("["):
                label = token_label(raw[1:-1])
                if label in inferred and inferred[label] != asset:
                    return False, {}
                inferred[label] = asset
        return True, inferred


def convert_target(entry, expected, mapping, allowed, config):
    """Convert DOCX markers to template assets; returns (text, repaired)."""
    target = strip_rule(entry["text"])
    try:
        return convert_tokens(target, allowed, config, mapping), False
    except ValueError as error:
        candidates = {}
        for raw in TOKEN.findall(strip_rule(entry["english"])):
            if raw.startswith("["):
                label = token_label(raw[1:-1])
                asset = mapping.get(label) or asset_name(raw[1:-1], config)
                if asset in allowed:
                    candidates[label] = asset
        try:
            return convert_tokens(repair_markers(target, entry["english"]), allowed, config, mapping, candidates), True
        except ValueError:
            raise error


def skeleton(text):
    """English sentence without its markers, used to compare DOCX English with the template."""
    return identity(TOKEN.sub(" ", strip_rule(text)))

def width(text, size, symbol_width):
    total = 0
    for part in re.split(r"(##[^#]+##)", text):
        if part.startswith("##"):
            total += symbol_width
        else:
            for char in part:
                if unicodedata.combining(char):
                    continue
                total += size * (1.05 if unicodedata.east_asian_width(char) in "WF" else 0.35 if char.isspace() else 0.7)
    return total


def wrap(text, size, config, continuation="   "):
    # Non-asset # characters include the engine's #currency# placeholder.
    atoms = re.findall(r"##[^#]+##|#currency#|[\s\S]", text)
    lines, line = [], ""
    for atom in atoms:
        if line and unicodedata.category(atom[0]).startswith("M"):
            line += atom  # never separate a vowel sign/diacritic from its base letter (Thai, Khmer…)
        elif line and width(line + atom, size, config["symbolWidth"]) > config["contentWidth"]:
            split = max(line.rfind(" "), line.rfind("\u200b"))
            if split > len(line) // 2 and not line[:split].endswith("•"):
                lines.append(line[:split].rstrip())
                line = continuation + line[split + 1:] + atom
            else:
                lines.append(line.rstrip())
                line = continuation + atom.lstrip()
        else:
            line += atom
    if line.strip():
        lines.append(line.rstrip())
    return lines

def cjk_chunks(text):
    """Break opportunities for Japanese/Chinese: katakana and kanji runs stay together, kana and
    punctuation that cannot start a line stay with the previous chunk."""
    def kind(char):
        code = ord(char)
        if 0x30A0 <= code <= 0x30FF:
            return "katakana"
        if 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF or char == "々":
            return "kanji"
        if 0x3040 <= code <= 0x309F or unicodedata.category(char).startswith("P"):
            return "attach"
        return "other"
    chunks, previous = [], None
    for char in text:
        current = kind(char)
        if chunks and (current == "attach" or (current == previous and current != "attach")):
            chunks[-1] += char
        else:
            chunks.append(char)
        previous = current if current != "attach" else "attach"
    # A single long run (e.g. Chinese) still needs a fallback: one character per chunk.
    return chunks if len(chunks) > 1 else list(text)


def balanced_lines(text, count):
    """Split text into count lines of similar length (keeps the English line structure)."""
    joiner = " "
    words = text.split()
    if len(words) <= 1 and "\u200b" in text:  # Khmer/Thai/Lao mark word breaks with zero-width spaces
        words, joiner = [word for word in text.split("\u200b") if word], "\u200b"
    elif len(words) <= 1 and any(unicodedata.east_asian_width(c) in "WF" for c in text):
        words, joiner = cjk_chunks(text), ""
    if count <= 1 or len(words) <= 1:
        return [text]
    count = min(count, len(words))

    @functools.lru_cache(maxsize=None)
    def best(start, lines):
        if lines == 1:
            return len(joiner.join(words[start:])), (len(words),)
        result = None
        for end in range(start + 1, len(words) - lines + 2):
            rest_width, rest_breaks = best(end, lines - 1)
            candidate = (max(len(joiner.join(words[start:end])), rest_width), (end, *rest_breaks))
            if result is None or candidate[0] < result[0]:
                result = candidate
        return result

    _, breaks = best(0, count)
    starts = (0, *breaks[:-1])
    return [joiner.join(words[a:b]) for a, b in zip(starts, breaks)]
