"""Import individual bilingual DOCX translations using the current game's English JSON."""
from __future__ import annotations

import argparse
import copy
import html
import json
import math
import re
import shutil
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the project free of __pycache__ folders
from modules.common import issue, read_json, write_json
from modules.extraction import extract_docx, select_documents
from modules.languages import requested_languages
from modules.text_processing import (BULLET, CONDITION, TOKEN, balanced_lines, clean, convert_target, direct_tokens,
                                        engine_width, identity, positional_token_mapping, skeleton, source_match,
                                        strip_rule, wrap, width)

BASE = Path(__file__).resolve().parent
FILES = ("info.json", "jackpotpages.json")


def blank_template(template):
    result = copy.deepcopy(template)
    result["rules"]["pages"] = []
    return result


def load_templates(folder):
    if not (folder / "info.json").is_file():
        raise ValueError(f"Falta la plantilla inglesa obligatoria: {folder / 'info.json'}")
    templates = {}
    for filename in FILES:
        path = folder / filename
        if not path.is_file():
            continue
        template = read_json(path)
        if not isinstance(template, dict) or not isinstance(template.get("rules", {}).get("pages"), list):
            raise ValueError(f"Plantilla inválida: {path}; se requiere rules.pages")
        templates[filename] = template
    return templates


def logical_rules(pages):
    rules = []
    has_bullets = any(BULLET.match(line) for page in pages for line in page.get("items", {}).get("lines", []))
    for page in pages:
        for line in page.get("items", {}).get("lines", []):
            if not line.strip():
                continue
            if BULLET.match(line) or not rules or not has_bullets:
                rules.append(clean(line))
            else:
                rules[-1] += " " + clean(line)
    return rules


def rule_spacing(pages):
    """Count template blank lines before each logical rule, not wrapped lines."""
    spacing, pending = [], 0
    has_bullets = any(BULLET.match(line) for page in pages for line in page.get("items", {}).get("lines", []))
    for page in pages:
        for line in page.get("items", {}).get("lines", []):
            if not line.strip():
                pending += 1
                continue
            if BULLET.match(line) or not spacing or not has_bullets:
                spacing.append(pending)
            pending = 0
    return spacing


def catalog_sections(templates):
    catalog = {}
    for filename, template in templates.items():
        for index, page in enumerate(template["rules"]["pages"]):
            if not page.get("items") or not page.get("titles"):
                continue
            title = page["titles"][0].get("text", "")
            key = identity(title)
            if not key:
                continue
            if key in catalog and catalog[key]["file"] != filename:
                raise ValueError(f"Título inglés ambiguo en distintos archivos: {title}")
            section = catalog.setdefault(key, dict(file=filename, title=title, indices=[], pages=[]))
            section["indices"].append(index)
            section["pages"].append(page)
    for section in catalog.values():
        section["rules"] = logical_rules(section["pages"])
    return catalog


def expand_parts(entries):
    expanded = []
    for entry in entries:
        if entry.get("parts"):
            expanded.extend(dict(number=f"{entry['number']}.{k}", english=part["english"], text=part["text"], parent=entry["number"])
                            for k, part in enumerate(entry["parts"], 1))
        else:
            expanded.append(entry)
    return expanded


def positional_entries(document, count):
    """DOCX rows aligned with the template rules, splitting multi-line cells when that fits."""
    entries = document["entries"]
    if len(entries) == count:
        return entries
    expanded = expand_parts(entries)
    return expanded if len(expanded) == count else None


def document_labels(sections, catalog, config):
    """Learn DOCX marker -> template asset pairs that are consistent across the whole document."""
    votes = {}
    for key, document in sections.items():
        section = catalog.get(key)
        if not section:
            continue
        entries = positional_entries(document, len(section["rules"])) or []
        for entry, expected in zip(entries, section["rules"]):
            if skeleton(entry["english"]) != skeleton(expected):
                continue
            for label, asset in positional_token_mapping(strip_rule(entry["english"]), strip_rule(expected)).items():
                votes.setdefault(label, set()).add(asset)
    return {label: assets.pop() for label, assets in votes.items() if len(assets) == 1}


def translate_rules(section, document, lang, source, config, allowed, report, known_labels=None):
    translations = [None] * len(section["rules"])
    if document is None:
        issue(report, lang, source, f"Sección ausente del DOCX; se conserva en inglés: {section['title']}")
        return translations, section["title"]
    known_labels = known_labels or {}
    matches = [[] for _ in section["rules"]]
    aligned = positional_entries(document, len(section["rules"])) if config.get("matching") == "position" else None
    positional = aligned is not None
    if config.get("matching") == "position" and not positional:
        issue(report, lang, source, f"Cantidad de reglas diferente en {section['title']}; se busca correspondencia por contenido")
    entries = aligned if positional else document["entries"] + [
        part for part in expand_parts(document["entries"]) if "parent" in part]
    unmatched = []
    for position, entry in enumerate(entries):
        if positional:
            index = position
            expected = section["rules"][index]
            _, mapping = source_match(entry["english"], expected, allowed, config, known_labels)
            mapping = {**known_labels, **positional_token_mapping(entry["english"], expected), **mapping}
            if skeleton(entry["english"]) != skeleton(expected):
                issue(report, lang, source, f"El inglés del DOCX difiere de la plantilla en {section['title']} regla {index + 1}; "
                      f"se usa la traducción por posición. DOCX: {entry['english']!r}")
            candidates = [(index, mapping)]
        else:
            candidates = [(i, {**known_labels, **mapping}) for i, expected in enumerate(section["rules"])
                          for matched, mapping in [source_match(entry["english"], expected, allowed, config, known_labels)]
                          if matched]
        if len(candidates) != 1:
            unmatched.append(entry)
            continue
        index, mapping = candidates[0]
        matches[index].append((entry, mapping))
    matched_numbers = {entry.get("parent", entry["number"]) for found in matches for entry, _ in found}
    for entry in unmatched:
        if entry.get("parent", entry["number"]) in matched_numbers:
            continue  # the same DOCX row was matched as a whole or line by line
        issue(report, lang, source, f"Fila {entry['number']} de {section['title']} sin correspondencia inequívoca; se conserva el inglés")
    for index, expected in enumerate(section["rules"]):
        reason = "traducción faltante o ambigua"
        if len(matches[index]) == 1:
            entry, mapping = matches[index][0]
            try:
                target, repaired = convert_target(entry, expected, mapping, allowed, config)
                if not re.search(r"[^\W\d_]", TOKEN.sub("", target)) or re.search(r"[•●]", target):
                    raise ValueError("texto vacío o varias viñetas")
                if sorted(TOKEN.findall(target)) != sorted(TOKEN.findall(strip_rule(expected))):
                    raise ValueError("los símbolos no coinciden con la regla inglesa "
                                     f"(plantilla: {', '.join(TOKEN.findall(strip_rule(expected))) or 'ninguno'}; "
                                     f"DOCX: {', '.join(TOKEN.findall(target)) or 'ninguno'})")
                if target.count("#currency#") != expected.count("#currency#"):
                    raise ValueError("falta el marcador de moneda")
                if identity(target) == identity(strip_rule(expected)):
                    raise ValueError("la traducción sigue en inglés")
                if "{fixedJackpot}" in target:
                    target = target.replace("{fixedJackpot}", "").strip()
                if repaired:
                    issue(report, lang, source, f"Marcador del DOCX corregido en {section['title']} regla {index + 1}: {entry['text']!r}")
                translations[index] = target
                continue
            except ValueError as error:
                reason = str(error)
        issue(report, lang, source, f"Inglés conservado: {section['title']} regla {index + 1}: {reason}")
    title = document["title"]
    if not title or not any(c.isalpha() for c in title) or identity(title) == identity(section["title"]):
        title = section["title"]
        issue(report, lang, source, f"Título conservado en inglés: {title}")
    return translations, title.upper()


def direct_rules(section, document, lang, source, config, allowed, report):
    """compareEnglish=false: take every DOCX translation in order, without checking its English column."""
    if document is None:
        issue(report, lang, source, f"Sección ausente del DOCX; se conserva en inglés: {section['title']}")
        return [None] * len(section["rules"]), section["title"]
    translations = []
    for entry in document["entries"]:
        target = strip_rule(entry["text"]).replace("{fixedJackpot}", "").strip()
        if not target:
            issue(report, lang, source, f"Fila {entry['number']} de {section['title']} sin traducción; se omite")
            continue
        original = target
        target, unresolved, repaired = direct_tokens(target, entry["english"], allowed, config)
        if repaired:
            issue(report, lang, source, f"Marcador del DOCX corregido en {section['title']} fila {entry['number']}: {original!r}")
        if unresolved:
            issue(report, lang, source, f"Marcador sin imagen conocida en {section['title']} fila {entry['number']}; "
                  f"se inserta tal cual: {', '.join(unresolved)}")
        unknown = sorted(set(re.findall(r"##([^#]+)##", target)) - allowed)
        if unknown:
            issue(report, lang, source, f"Imagen no usada por la plantilla inglesa en {section['title']} "
                  f"fila {entry['number']}: {', '.join(unknown)}")
        translations.append(target)
    if translations and len(translations) != len(section["rules"]):
        issue(report, lang, source, f"{section['title']}: el DOCX tiene {len(translations)} textos y la plantilla "
              f"{len(section['rules'])} reglas; se insertan todos los textos del DOCX")
    title = document["title"].strip()
    if not title:
        title = section["title"]
        issue(report, lang, source, f"Título conservado en inglés: {title}")
    return translations, title.upper()


def rule_indent(line):
    """Leading spaces of a template rule (sub-bullets are indented)."""
    return re.match(r"[ \t]*", CONDITION.sub("", line)).group()


def logical_indents(pages):
    indents = []
    has_bullets = any(BULLET.match(line) for page in pages for line in page.get("items", {}).get("lines", []))
    for page in pages:
        for line in page.get("items", {}).get("lines", []):
            if line.strip() and (BULLET.match(line) or not indents or not has_bullets):
                indents.append(rule_indent(line))
    return indents


def fit_resolution(prototypes, settings, resolution):
    """Text width and lines per page inside the configured image, whose centre is the items' origin.

    The engine draws each line left-aligned at offset x and steps down by gap from offset y."""
    image_width, image_height = float(resolution["width"]), float(resolution["height"])
    left = -image_width / 2 + float(resolution.get("paddingLeft", 0))
    right = image_width / 2 - float(resolution.get("paddingRight", 0))
    bottom = image_height / 2 - float(resolution.get("paddingBottom", 0))
    fitted, widths, capacities = [], [], []
    for page in prototypes:
        page = copy.deepcopy(page)
        override = page["items"].get("setting", {})
        font = {**settings.get("font", {}), **override.get("font", {})}
        size = float(font.get("size", 26))
        gap = float(override.get("gap", settings.get("gap", 30)))
        x, y = (float(value) for value in override.get("offset", settings.get("offset", "0,200")).split(","))
        if x < left:  # the template text would start outside the padded image
            page["items"].setdefault("setting", {})["offset"] = f"{left:g},{y:g}"
            x = left
        if right - x <= 0:
            raise ValueError("resolution no deja ancho para el texto; revisa width y paddingLeft/paddingRight")
        fitted.append(page)
        widths.append(right - x)
        capacities.append(max(1, math.floor((bottom - size / 2 + y) / gap) + 1))
    return fitted, widths, capacities


def line_measure(template, config):
    """Line width function that reproduces how the game draws text and inline icons."""
    settings = template["rules"].get("settings", {}).get("items", {})
    symbols = settings.get("symbols", {})
    stroke = float(settings.get("font", {}).get("stroke", {}).get("size", 0))
    textures = config.get("symbolTextureWidths", {})
    default_texture = float(config.get("symbolTextureWidth", 400))

    def icon(asset):
        # Same lookup as the engine: symbols[<name without extension>] or symbols.default, scale 0.4.
        setting = symbols.get(asset.split(".")[0]) or symbols.get("default") or {}
        return (float(textures.get(asset, default_texture)) * float(setting.get("scale") or 0.4),
                float(setting.get("gapX") or 0))
    return lambda text, size, _symbol_width=None: engine_width(text, size, icon, stroke)


def paginate_section(template, section, translations, title, config, lang, report, subtitles=None):
    prototypes = section["pages"]
    settings = template["rules"].get("settings", {}).get("items", {})
    sizes, capacities = [], []
    for page in prototypes:
        override = page["items"].get("setting", {})
        sizes.append(override.get("font", {}).get("size", settings.get("font", {}).get("size", 26)))
        gap = float(override.get("gap", settings.get("gap", 30)))
        y = float(override.get("offset", settings.get("offset", "0,200")).split(",")[1])
        if gap <= 0:
            raise ValueError(f"Espaciado inválido en {section['title']}")
        capacities.append(max(1, math.floor((y - config["bottomY"]) / gap) + 1))
    size, capacity = max(sizes), min(capacities)
    resolution, measure, widths = config.get("resolution"), width, None
    if resolution:
        # Fit the text in the configured image instead of the rough contentWidth/bottomY estimate.
        prototypes, widths, capacities = fit_resolution(prototypes, settings, resolution)
        measure, capacity = line_measure(template, config), min(capacities)
        config = {**config, "contentWidth": min(widths)}
    elif config.get("layout") == "template":
        # The English layout is stronger evidence than the rough font estimate.
        authored_width = max((width(line, size, config["symbolWidth"])
                              for page in template["rules"]["pages"]
                              for line in page.get("items", {}).get("lines", []) if line.strip()), default=0)
        config = {**config, "contentWidth": max(config["contentWidth"], authored_width)}
        authored_bottom = min((
            float(page.get("items", {}).get("setting", {}).get("offset", settings.get("offset", "0,200")).split(",")[1])
            - (len(page.get("items", {}).get("lines", [])) - 1)
            * float(page.get("items", {}).get("setting", {}).get("gap", settings.get("gap", 30)))
            for page in template["rules"]["pages"] if page.get("items", {}).get("lines")), default=config["bottomY"])
        bottom = min(config["bottomY"], authored_bottom)
        capacities = [max(cap, math.floor((float(page["items"].get("setting", {}).get(
            "offset", settings.get("offset", "0,200")).split(",")[1]) - bottom) /
            float(page["items"].get("setting", {}).get("gap", settings.get("gap", 30)))) + 1)
            for page, cap in zip(prototypes, capacities)]
        capacity = min(capacities)
    default_title_size = template["rules"].get("settings", {}).get("titles", {}).get("font", {}).get("size", 55)
    title_size = max(page["titles"][0].get("size", default_title_size) for page in prototypes)
    title_width = (float(resolution["width"]) - float(resolution.get("paddingLeft", 0))
                   - float(resolution.get("paddingRight", 0))) if resolution else config["contentWidth"]
    if any(measure(line, title_size, config["symbolWidth"]) > title_width for line in title.splitlines()):
        issue(report, lang, section["file"], f"Revisar ancho del título: {title}")
    if config.get("layout") == "template" or any(len(page.get("titles", [])) > 1 for page in prototypes):
        return paginate_authored_pages(prototypes, translations, title, subtitles or {}, sizes, capacities, config, settings,
                                       widths, measure)
    spacing = rule_spacing(prototypes)
    indents = logical_indents(prototypes)
    batches, current = [], []
    for rule_index, target in enumerate(translations):
        # Extra DOCX texts (compareEnglish=false) take the format of the last English rule.
        style = min(rule_index, len(section["rules"]) - 1)
        expected = section["rules"][style]
        condition = "{fixedJackpot}" if CONDITION.match(expected) else ""
        indent = indents[style] if BULLET.match(expected) else ""
        bullet = indent + "• " if BULLET.match(expected) else ""
        lines = wrap(bullet + (target if target is not None else strip_rule(expected)), size, config, indent + "   ",
                     measure)
        separators = spacing[style]
        if current and len(current) + len(lines) + separators > capacity:
            batches.append(current)
            current = []
        elif separators:
            current.extend([""] * min(separators, capacity - len(current)))
        for line in lines:
            if len(current) == capacity:
                batches.append(current)
                current = []
            current.append(condition + line)
    if current:
        batches.append(current)
    result = []
    for index, lines in enumerate(batches):
        page = copy.deepcopy(prototypes[min(index, len(prototypes) - 1)])
        page["titles"][0]["text"] = title
        page["items"]["lines"] = lines
        result.append(page)
    return result


def paginate_authored_pages(prototypes, translations, title, subtitles, sizes, capacities, config, settings,
                            widths=None, measure=width):
    """Flow complete rules within subtitle blocks instead of expanding each old page."""
    rules, starts = [], []
    has_bullets = any(BULLET.match(line) for page in prototypes for line in page["items"]["lines"])
    gaps = []
    for page_index, page in enumerate(prototypes):
        previous = None
        for line_index, line in enumerate(page["items"]["lines"]):
            if not line.strip():
                continue
            if previous is not None:
                gaps.append(line_index - previous - 1)
            previous = line_index
            if BULLET.match(line) or not rules or not has_bullets:
                rules.append(clean(line))
                starts.append((page_index, line_index))
            else:
                rules[-1] += " " + clean(line)
    indents = logical_indents(prototypes)
    # Some engines space every visual line, including wrapped continuation lines.
    visual_gap = min(gaps) if gaps and all(gap > 0 for gap in gaps) else 0
    spacing = rule_spacing(prototypes)
    anchors = {}
    top_deltas = []
    for page_index, page in enumerate(prototypes):
        override = page["items"].get("setting", {})
        y = float(override.get("offset", settings.get("offset", "0,200")).split(",")[1])
        gap = float(override.get("gap", settings.get("gap", 30)))
        for heading in page.get("titles", [])[1:]:
            offset = heading.get("offset")
            line_index = 0
            if offset:
                heading_y = float(offset.split(",")[1])
                line_index = max(0, math.ceil((y - heading_y) / gap))
                if heading_y >= y:
                    top_deltas.append(heading_y - y)
            index = next((i for i, start in enumerate(starts) if start >= (page_index, line_index)), len(rules))
            if index < len(rules):
                anchors.setdefault(index, []).append((page_index, heading))
    # With compareEnglish=false the DOCX may have more or fewer texts than the English rules.
    boundaries = sorted({0, len(translations), *(index for index in anchors if index < len(translations))})
    result = []
    for start, end in zip(boundaries, boundaries[1:]):
        if start == end:
            continue
        heading_refs = anchors.get(start, [])
        owner = heading_refs[0][0] if heading_refs else starts[start][0]
        prototype = copy.deepcopy(prototypes[owner])
        prototype["titles"] = prototype["titles"][:1]
        prototype["titles"][0]["text"] = title
        prefix = spacing[start] if start == 0 else 0
        if heading_refs:
            item_y = float(prototype["items"].get("setting", {}).get(
                "offset", settings.get("offset", "0,200")).split(",")[1])
            for _, original_heading in heading_refs:
                heading = copy.deepcopy(original_heading)
                translated = subtitles.get(identity(heading.get("text", "")))
                if translated:
                    heading["text"] = translated
                if heading.get("offset"):
                    x, old_y = heading["offset"].split(",")
                    new_y = item_y + (min(top_deltas) if top_deltas else 10)
                    heading["offset"] = f"{x},{new_y:g}"
                prototype["titles"].append(heading)
            # Use the padding of a top-aligned subtitle in the English layout.
            top_padding = [spacing[i] for i, refs in anchors.items()
                           if starts[i][0] == refs[0][0] and starts[i][1] <= 3]
            prefix = max(top_padding, default=2 if any(h.get("offset") for _, h in heading_refs) else 0)
        capacity = capacities[owner]
        size = sizes[owner]
        page_config = {**config, "contentWidth": widths[owner]} if widths else config
        current = [""] * min(prefix, max(0, capacity - 1))
        first_page = True

        def emit():
            nonlocal current, first_page
            while current and not current[-1].strip():
                current.pop()
            if not any(line.strip() for line in current):
                current = []
                return
            page = copy.deepcopy(prototype)
            if not first_page:
                page["titles"] = page["titles"][:1]
            page["items"]["lines"] = current
            result.append(page)
            current = []
            first_page = False

        for index in range(start, end):
            style = min(index, len(rules) - 1)
            expected, target = rules[style], translations[index]
            condition = "{fixedJackpot}" if CONDITION.match(expected) else ""
            indent = indents[style] if BULLET.match(expected) else ""
            bullet = indent + "• " if BULLET.match(expected) else ""
            wrapped = wrap(bullet + (target if target is not None else strip_rule(expected)), size, page_config,
                           indent + "   ", measure)
            lines = []
            for line in wrapped:
                if lines:
                    lines.extend([""] * visual_gap)
                lines.append(condition + line)
            separator = max(visual_gap, spacing[style]) if index > start else 0
            if any(line.strip() for line in current) and len(current) + separator + len(lines) > capacity:
                emit()
                separator = 0
            if any(line.strip() for line in current):
                current.extend([""] * separator)
            if len(current) + len(lines) <= capacity:
                current.extend(lines)
            else:
                # Split only rules that cannot fit on an otherwise empty page.
                for line in lines:
                    if len(current) >= capacity:
                        emit()
                    if line.strip() or current:
                        current.append(line)
        emit()
    return result


def build_locale(template, filename, catalog, documents, lang, source, config, report, allowed, known_labels=None):
    result = blank_template(template)
    replacements, skipped = {}, set()
    for key, section in catalog.items():
        if section["file"] != filename:
            continue
        if config.get("compareEnglish", True):
            translations, title = translate_rules(section, documents.get(key), lang, source, config, allowed, report,
                                                  known_labels)
        else:
            translations, title = direct_rules(section, documents.get(key), lang, source, config, allowed, report)
        if not any(text is not None for text in translations):
            pages = copy.deepcopy(section["pages"])
            if documents.get(key):
                for page in pages:
                    page["titles"][0]["text"] = title
        else:
            pages = paginate_section(template, section, translations, title, config, lang, report,
                                     documents.get(key, {}).get("subtitles", {}))
        replacements[section["indices"][0]] = pages
        skipped.update(section["indices"][1:])
    for index, page in enumerate(template["rules"]["pages"]):
        if index in replacements:
            result["rules"]["pages"].extend(replacements[index])
        elif index not in skipped:
            result["rules"]["pages"].append(copy.deepcopy(page))
    return result


def free_text_fields(value, inside_rules=False):
    """Yield dicts with a 'text' outside rules (paytable and payline titles)."""
    if isinstance(value, dict):
        if not inside_rules and isinstance(value.get("text"), str):
            yield value
        for key, child in value.items():
            yield from free_text_fields(child, inside_rules or key == "rules")
    elif isinstance(value, list):
        for child in value:
            yield from free_text_fields(child, inside_rules)


def translate_free_texts(data, labels, lang, source, filename, report):
    """Translate texts outside rules with the DOCX 'ENG: … / LANGUAGE: …' notes, matching the English exactly."""
    lookup, with_symbols = {}, set()
    for pair in labels:
        key, text = identity(pair["english"]), clean(pair["text"])
        if TOKEN.search(pair["english"]) or TOKEN.search(text):
            with_symbols.add(identity(TOKEN.sub(" ", pair["english"])))
            continue
        if key and key not in lookup and re.search(r"[^\W\d_]", text) and identity(text) != key:
            lookup[key] = text
    missing, manual = [], []
    for field in free_text_fields(data):
        english = field["text"]
        key = identity(english)
        if not key:
            continue
        translated = lookup.get(key)
        if not translated:
            (manual if key in with_symbols else missing).append(clean(english))
            continue
        lines = [line for line in english.split("\n") if line.strip()]
        if english.upper() == english:
            translated = translated.upper()
        field["text"] = "\n".join(balanced_lines(translated, len(lines)))
    if missing:
        issue(report, lang, source, f"{filename}: textos fuera de reglas sin traducción en el DOCX; se conservan en inglés: "
              + ", ".join(dict.fromkeys(missing)))
    if manual:
        issue(report, lang, source, f"{filename}: texto con símbolo intercalado; requiere ajuste manual, se conserva en inglés: "
              + ", ".join(dict.fromkeys(manual)))
    return data


def preview(outputs, path):
    body = ['<!doctype html><html lang="es"><meta charset="utf-8"><title>uploadLanguage</title>',
            '<style>body{background:#171717;color:#eee;font:18px Arial;margin:30px}article{background:#3c1309;padding:30px;margin:20px 0;max-width:1100px}h2{color:#eeff0f}p{white-space:pre-wrap}code{color:#60d7ee}</style>',
            '<h1>uploadLanguage</h1><p>Vista aproximada del texto. Revisar el diseño final en el juego y las advertencias de report.json.</p>']
    for lang, files in outputs.items():
        body.append(f'<h1>{html.escape(lang)}</h1>')
        for filename, data in files.items():
            body.append(f'<h2>{html.escape(filename)}</h2>')
            for page in data["rules"]["pages"]:
                body.append('<article>')
                for title in page.get("titles", []):
                    body.append(f'<h2>{html.escape(title.get("text", ""))}</h2>')
                for line in page.get("items", {}).get("lines", []):
                    body.append(f'<p>{html.escape(line)}</p>')
                body.append('</article>')
    path.write_text("\n".join(body) + '</html>', encoding="utf-8")


def reset_output(output, root, documents, templates):
    target = output.resolve()
    if target != root.resolve() / "output" or output.is_symlink():
        raise ValueError("Reset solo permite la carpeta output dentro de uploadLanguage")
    for protected in (documents.resolve(), templates.resolve()):
        if target == protected or target in protected.parents or protected in target.parents:
            raise ValueError(f"Reset bloqueado: output coincide con datos de origen: {protected}")
    if output.exists():
        if not output.is_dir():
            raise ValueError("output no es una carpeta")
        shutil.rmtree(output)
    print("Output eliminado; documentos, configuración y plantillas conservados.")


def validate_resolution(resolution):
    if resolution is None:
        return
    keys = ("width", "height", "paddingLeft", "paddingRight", "paddingBottom")
    if not isinstance(resolution, dict) or any(
            not isinstance(resolution.get(key, 0), (int, float)) or resolution.get(key, 0) < 0 for key in keys):
        raise ValueError("resolution debe tener width, height y paddings numéricos no negativos")
    if resolution.get("width", 0) <= 0 or resolution.get("height", 0) <= 0:
        raise ValueError("resolution.width y resolution.height deben ser mayores que 0")
    if resolution.get("paddingLeft", 0) + resolution.get("paddingRight", 0) >= resolution["width"]:
        raise ValueError("paddingLeft + paddingRight debe ser menor que resolution.width")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=BASE / "config.json")
    parser.add_argument("--lang", help="Idiomas separados por coma; por defecto los DOCX disponibles")
    parser.add_argument("--reset", action="store_true", help="Borrar output")
    args = parser.parse_args(argv)
    config = {"contentWidth": 1100, "bottomY": -290, "symbolWidth": 75, **read_json(args.config)}
    validate_resolution(config.get("resolution"))
    root = args.config.resolve().parent
    documents, template_folder, output = ((root / config[key]).resolve() for key in ("documents", "templates", "output"))
    if args.reset:
        if args.lang:
            raise ValueError("Usa --reset separado de --lang")
        reset_output(root / config["output"], root, documents, template_folder)
        return 0
    requested = requested_languages(args.lang)
    templates = load_templates(template_folder)
    catalog = catalog_sections(templates)
    output.mkdir(parents=True, exist_ok=True)
    for filename, template in templates.items():
        write_json(output / "templates" / filename, blank_template(template))
    with select_documents(root, config, requested) as (documents, found, ignored, document_sources, download_failures):
        selected = requested if requested is not None else list(dict.fromkeys([*found, *download_failures]))
        report, outputs, extracted, extracted_texts = [], {}, {}, {}
        if not selected:
            issue(report, "all", documents, "No hay DOCX de los 14 idiomas individuales. Agrega, por ejemplo, GERMAN.docx; los documentos compartidos no se leen", "error")
        for lang, error in download_failures.items():
            issue(report, lang, config["googleDriveUrl"], f"No se pudo descargar el DOCX desde Google Drive: {error}", "error")
        allowed = set(re.findall(r"##([^#]+)##", json.dumps(templates)))
        for lang in selected:
            if lang not in found:
                if lang not in download_failures:
                    issue(report, lang, documents, "Falta el DOCX del idioma solicitado", "error")
                continue
            source = found[lang]
            try:
                labels = []
                sections = extract_docx(source, lang, report, templates, labels, config.get("compareEnglish", True))
                extracted[lang] = sections
                extracted_texts[lang] = labels
                if config.get("matching") == "position":
                    if len(sections) == len(catalog):
                        sections = dict(zip(catalog, sections.values()))
                    else:
                        issue(report, lang, source.name, "Cantidad de secciones diferente; se asocian por título inglés")
                for key, section in sections.items():
                    if key not in catalog:
                        issue(report, lang, source.name, f"Sección no presente en la plantilla inglesa; no se importa: {section['englishTitle']}")
                known_labels = document_labels(sections, catalog, config) if config.get("compareEnglish", True) else {}
                outputs[lang] = {filename: translate_free_texts(
                    build_locale(template, filename, catalog, sections, lang, source.name, config, report, allowed,
                                 known_labels), labels, lang, source.name, filename, report)
                                 for filename, template in templates.items()}
                for filename, data in outputs[lang].items():
                    write_json(output / "lang" / lang / "info" / filename, data)
            except Exception as error:
                outputs.pop(lang, None)
                issue(report, lang, source.name, f"No se pudo procesar el DOCX: {error}", "error")
        write_json(output / "extracted.json", extracted)
        write_json(output / "extracted-texts.json", extracted_texts)
        write_json(output / "report.json", report)
        write_json(output / "template-manifest.json", dict(mode="english-json-docx", templates={
            name: str(template_folder / name) for name in templates},
            sections={section["title"]: dict(file=section["file"], rules=len(section["rules"])) for section in catalog.values()},
            documents={lang: document_sources[lang] for lang in selected if lang in found}, ignoredDocuments=ignored))
        preview(outputs, output / "preview.html")
        errors = sum(entry["severity"] == "error" for entry in report)
        print(f"Generated {sum(len(files) for files in outputs.values())} JSON files. Errors: {errors}; warnings: {len(report) - errors}.")
        print(f"Preview: {output / 'preview.html'}\nReport: {output / 'report.json'}")
        return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
