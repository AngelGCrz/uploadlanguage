"""JSON helpers and report entries shared by every module."""
from __future__ import annotations

import json


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def issue(report, lang, source, message, severity="warning"):
    report.append(dict(language=lang, source=str(source), severity=severity, message=message))
