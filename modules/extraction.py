"""Locate the DOCX of each language (local folder or Google Drive) and extract their bilingual tables."""
from __future__ import annotations

import contextlib
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from docx import Document
from docx.table import Table

from .common import issue
from .languages import language_for, language_prefixes
from .text_processing import clean, header, identity

try:
    import gdown
except ImportError:  # Report a helpful configuration error when dependencies were not installed.
    gdown = None

GOOGLE_DRIVE_HOSTS = {"drive.google.com", "www.drive.google.com"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
# "ENG: text" followed by "<LANGUAGE>: translation" inside free-form cells (paytable notes).
LABEL = re.compile(r"^\s*([^\W\d_][^\W\d_ ]{1,19}(?: [^\W\d_]{2,19})?)\s*:\s*(.*)$")


def find_documents(documents, config):
    prefixes = language_prefixes(config)
    found, ignored = {}, []
    for path in sorted(documents.glob("*")):
        if not path.is_file() or path.suffix.casefold() != ".docx" or path.name.lstrip().startswith("~$"):
            continue
        lang = language_for(path, prefixes)
        if lang is None:
            ignored.append(path.name)
            continue
        if lang in found:
            raise ValueError(f"Dos DOCX corresponden a {lang}: {found[lang].name} y {path.name}; deja solo uno")
        found[lang] = path
    return found, ignored


def is_google_drive_folder_url(value):
    """Return whether value is a Google Drive folder URL accepted by gdown."""
    parsed = urlparse(value or "")
    return (parsed.scheme in {"http", "https"} and parsed.hostname in GOOGLE_DRIVE_HOSTS
            and "/folders/" in parsed.path)


def download_google_drive_folder(url, destination, config, requested=None):
    if not is_google_drive_folder_url(url):
        raise ValueError("googleDriveUrl debe ser un enlace a una carpeta de Google Drive")
    if gdown is None:
        raise ValueError("Falta la dependencia gdown; instala requirements.txt antes de usar googleDriveUrl")
    entries = gdown.download_folder(url=url, output=str(destination), quiet=True,
                                    remaining_ok=True, skip_download=True)
    if not entries:
        raise ValueError("No se pudo leer googleDriveUrl; verifica que la carpeta sea pública")
    prefixes = language_prefixes(config)
    available = {}
    for entry in entries:
        path = Path(entry.path)
        if path.suffix.casefold() != ".docx" or path.name.lstrip().startswith("~$"):
            continue
        lang = language_for(path, prefixes)
        if lang is None:
            continue
        if lang in available:
            raise ValueError(f"Dos DOCX corresponden a {lang}: {available[lang].path} y {entry.path}; deja solo uno")
        available[lang] = entry
    failures = {}
    for lang, entry in available.items():
        if requested is not None and lang not in requested:
            continue
        destination_path = destination / Path(entry.path).name
        try:
            downloaded = gdown.download(id=entry.id, output=str(destination_path), quiet=True)
            if not downloaded:
                raise ValueError("Google Drive no devolvió un archivo")
        except Exception as error:
            failures[lang] = str(error)
    return failures


@contextlib.contextmanager
def select_documents(root, config, requested=None):
    """Use local DOCX files first, then a configured public Drive folder as fallback."""
    local_documents = (root / config["documents"]).resolve()
    found, ignored = find_documents(local_documents, config)
    drive_url = config.get("googleDriveUrl")
    if found or not drive_url:
        yield local_documents, found, ignored, {lang: str(path) for lang, path in found.items()}, {}
        return
    with tempfile.TemporaryDirectory(prefix="uploadlanguage-drive-") as temporary:
        drive_documents = Path(temporary)
        failures = download_google_drive_folder(drive_url, drive_documents, config, requested)
        found, ignored = find_documents(drive_documents, config)
        yield (drive_documents, found, ignored, {lang: f"{drive_url} ({path.name})" for lang, path in found.items()},
               failures)


def _collect_text(element, parts):
    """Append the visible text of element, including content controls and tracked insertions."""
    for child in element:
        tag = child.tag
        if tag == MC_FALLBACK or tag == W + "tbl" or tag == W + "del":
            continue  # Fallback duplicates mc:Choice; nested tables are read on their own.
        if tag == W + "t":
            parts.append(child.text or "")
        elif tag == W + "tab":
            parts.append("\t")
        elif tag in (W + "br", W + "cr"):
            parts.append("\n")
        else:
            _collect_text(child, parts)


def _paragraph_elements(element):
    for child in element:
        if child.tag == W + "p":
            yield child
        elif child.tag not in (W + "tbl", MC_FALLBACK):
            yield from _paragraph_elements(child)


def cell_paragraphs(cell):
    """Paragraph texts of a cell. python-docx's cell.text skips text inside w:sdt (Google Docs exports)."""
    paragraphs = []
    for paragraph in _paragraph_elements(cell._tc):
        parts = []
        _collect_text(paragraph, parts)
        paragraphs.extend("".join(parts).split("\n"))
    return paragraphs


def cell_text(cell):
    return "\n".join(cell_paragraphs(cell))


def document_tables(document):
    """All top-level tables in reading order, including tables wrapped in content controls."""
    body = document.element.body
    for element in body.iter(W + "tbl"):
        parent, nested = element.getparent(), False
        while parent is not None and parent is not body:
            if parent.tag == W + "tbl":
                nested = True
                break
            parent = parent.getparent()
        if not nested:
            yield Table(element, document._body)


def labelled_pairs(paragraphs):
    """Read 'ENG: source' / '<LANGUAGE>: translation' notes written inside a cell."""
    pairs, current, field = [], None, None
    for raw in paragraphs:
        line = clean(raw)
        if not line:
            continue
        match = LABEL.match(line)
        label = header(match[1]) if match else ""
        if match and label in {"ENG", "ENGLISH", "INGLES"}:
            current = dict(english=match[2], text="")
            pairs.append(current)
            field = "english"
        elif match and current is not None and field == "english":
            current["text"], field = match[2], "text"
        elif current is not None and field:
            current[field] = clean(current[field] + " " + line)
    return [pair for pair in pairs if clean(pair["english"])]


def split_parts(english_paragraphs, target_paragraphs):
    """Pair the lines of a multi-line cell (e.g. sub-bullets) when both columns have the same count."""
    english = [clean(text) for text in english_paragraphs if clean(text)]
    target = [clean(text) for text in target_paragraphs if clean(text)]
    if len(english) > 1 and len(english) == len(target):
        return [dict(english=e, text=t) for e, t in zip(english, target)]
    return []


def extract_docx(path, lang, report, templates=None, labels=None, compare_english=True):
    """Return the bilingual rule sections; 'ENG:' notes are appended to labels when given."""
    sections, active = {}, None
    labels = [] if labels is None else labels
    subtitle_keys = {identity(title.get("text", ""))
                     for template in (templates or {}).values()
                     for page in template["rules"]["pages"]
                     for title in page.get("titles", [])[1:]}
    english_column = target_column = None
    for table in document_tables(Document(path)):
        rows = list(table.rows)
        if not rows:
            continue
        headers = [header(cell_text(cell)) for cell in rows[0].cells]
        english = next((i for i, name in enumerate(headers) if name in {"INGLES", "ENGLISH", "ENG"}), None)
        start = 0
        if english is not None:
            target = next((i for i in range(english + 1, len(headers)) if headers[i]), None)
            if target is None and english + 1 < len(headers):
                target = english + 1
            if target is None or len(rows) < 2:
                issue(report, lang, path.name, "Tabla sin columna de traducción o sin título; se conserva el inglés")
                active = None
                continue
            english_column, target_column = english, target
            if clean(cell_text(rows[1].cells[0])).isdigit() and active is not None:
                start = 1
            else:
                title = clean(cell_text(rows[1].cells[english]))
                key = identity(title)
                if not key:
                    active = None
                    continue
                active = sections.setdefault(key, dict(englishTitle=title,
                    title=cell_text(rows[1].cells[target]).strip(), entries=[]))
                start = 2
        elif active is None or max(english_column, target_column) >= len(rows[0].cells):
            # Free-form tables (paytable notes, headings) are not rule tables.
            for row in rows:
                seen = []
                for cell in row.cells:
                    if any(cell._tc is other for other in seen):
                        continue
                    seen.append(cell._tc)
                    labels.extend(labelled_pairs(cell_paragraphs(cell)))
            continue
        previous = None
        for row in rows[start:]:
            cells = row.cells
            if max(english_column, target_column) >= len(cells):
                issue(report, lang, path.name, "Fila con columnas incompletas; se conserva el inglés")
                continue
            # A vertically merged cell repeats the same rule on the following row.
            if previous is not None and cells[english_column]._tc is previous[english_column]._tc:
                continue
            previous = cells
            source = clean(cell_text(cells[english_column]))
            texts = list(dict.fromkeys(clean(cell_text(cell)) for cell in cells[target_column:] if clean(cell_text(cell))))
            # Without the English comparison a translated row is read even if its English cell is empty.
            if not source and (compare_english or not texts):
                continue
            target_cells, target_paragraphs = [], []
            for cell in cells[target_column:]:
                if any(cell._tc is other for other in target_cells) or not clean(cell_text(cell)):
                    continue
                target_cells.append(cell._tc)
                target_paragraphs.extend(cell_paragraphs(cell))
            if source and identity(source) in subtitle_keys:
                active.setdefault("subtitles", {})[identity(source)] = " ".join(texts)
                continue
            entry = dict(number=len(active["entries"]) + 1, english=source, text=" ".join(texts))
            parts = split_parts(cell_paragraphs(cells[english_column]), target_paragraphs)
            if parts:
                entry["parts"] = parts
            active["entries"].append(entry)
    if not sections:
        issue(report, lang, path.name, "No se encontraron tablas bilingües; todos los textos quedan en inglés")
    return sections

