from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MARKDOWN_EXTENSIONS = {".md", ".markdown"}
PDF_EXTENSIONS = {".pdf"}
ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".avif",
}
EXCLUDED_DIRS = {
    ".git",
    ".github",
    ".obsidian",
    ".quarto",
    ".venv",
    "__pycache__",
    "_site",
    "_freeze",
    "site_libs",
    "generated",
    "scripts",
}
EXCLUDED_FILES = {
    "index.qmd",
    "browse.qmd",
    "README.md",
    "_quarto.yml",
    "styles.css",
    "site.js",
}


@dataclass
class Entry:
    source: Path
    relative: Path
    subject: str
    title: str
    kind: str
    target: Path


def slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "item"


def visible_parts(path: Path) -> list[str]:
    return [part for part in path.parts if part not in {".", ""}]


def is_excluded(path: Path, project_root: Path) -> bool:
    rel = path.relative_to(project_root)
    if rel.name in EXCLUDED_FILES:
        return True
    return any(part in EXCLUDED_DIRS for part in rel.parts)


def discover_files(project_root: Path) -> tuple[list[Path], list[Path], list[Path]]:
    notes: list[Path] = []
    pdfs: list[Path] = []
    assets: list[Path] = []

    for path in project_root.rglob("*"):
        if path.is_dir():
            continue
        if is_excluded(path, project_root):
            continue
        suffix = path.suffix.lower()
        if suffix in MARKDOWN_EXTENSIONS:
            notes.append(path)
        elif suffix in PDF_EXTENSIONS:
            pdfs.append(path)
        elif suffix in ASSET_EXTENSIONS:
            assets.append(path)

    return sorted(notes), sorted(pdfs), sorted(assets)


def extract_title(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()

    return path.stem.replace("-", " ").replace("_", " ").strip().title()


def build_entries(project_root: Path, notes: list[Path], pdfs: list[Path]) -> tuple[list[Entry], list[Entry]]:
    note_entries: list[Entry] = []
    pdf_entries: list[Entry] = []

    for source in notes:
        relative = source.relative_to(project_root)
        subject = visible_parts(relative)[0] if len(visible_parts(relative)) > 1 else "General"
        target = Path("generated") / "notes" / relative.with_suffix(".qmd")
        note_entries.append(
            Entry(
                source=source,
                relative=relative,
                subject=subject,
                title=extract_title(source),
                kind="note",
                target=target,
            )
        )

    for source in pdfs:
        relative = source.relative_to(project_root)
        subject = visible_parts(relative)[0] if len(visible_parts(relative)) > 1 else "General"
        target = Path("generated") / "pdfs" / relative.with_suffix(".qmd")
        pdf_entries.append(
            Entry(
                source=source,
                relative=relative,
                subject=subject,
                title=source.stem.replace("-", " ").replace("_", " ").strip().title(),
                kind="pdf",
                target=target,
            )
        )

    return note_entries, pdf_entries


def grouped_subjects(entries: Iterable[Entry]) -> dict[str, list[Entry]]:
    subjects: dict[str, list[Entry]] = {}
    for entry in entries:
        subjects.setdefault(entry.subject, []).append(entry)
    return dict(sorted(subjects.items(), key=lambda item: item[0].lower()))


def build_note_lookup(entries: list[Entry]) -> dict[str, list[Entry]]:
    lookup: dict[str, list[Entry]] = {}
    for entry in entries:
        keys = {
            normalize_wikilink(entry.relative.as_posix()),
            normalize_wikilink(entry.relative.with_suffix("").as_posix()),
            normalize_wikilink(entry.relative.stem),
        }
        for key in keys:
            lookup.setdefault(key, []).append(entry)
    return lookup


def normalize_wikilink(value: str) -> str:
    cleaned = value.strip().replace("\\", "/")
    cleaned = re.sub(r"\.md$|\.markdown$", "", cleaned, flags=re.IGNORECASE)
    return slugify(cleaned)


def replace_wikilinks(markdown: str, current_entry: Entry, lookup: dict[str, list[Entry]]) -> str:
    def repl(match: re.Match[str]) -> str:
        target_text = match.group(1).strip()
        alias = (match.group(2) or target_text).strip()
        key = normalize_wikilink(target_text)
        candidates = lookup.get(key, [])

        if not candidates:
            return alias

        chosen = choose_candidate(current_entry, target_text, candidates)
        href = relative_href(current_entry.target, chosen.target)
        return f"[{alias}]({href})"

    pattern = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
    return pattern.sub(repl, markdown)


def choose_candidate(current_entry: Entry, raw_target: str, candidates: list[Entry]) -> Entry:
    normalized_path = normalize_wikilink(raw_target)
    for candidate in candidates:
        if normalize_wikilink(candidate.relative.as_posix()) == normalized_path:
            return candidate

    sibling_subject_matches = [item for item in candidates if item.subject == current_entry.subject]
    if len(sibling_subject_matches) == 1:
        return sibling_subject_matches[0]

    return candidates[0]


def rewrite_asset_links(markdown: str, current_entry: Entry, project_root: Path) -> str:
    pattern = re.compile(r"(!?\[.*?\])\(([^)]+)\)")

    def repl(match: re.Match[str]) -> str:
        label, target = match.groups()
        clean_target = target.strip()
        if clean_target.startswith(("http://", "https://", "#", "mailto:")):
            return match.group(0)
        if clean_target.startswith("<") and clean_target.endswith(">"):
            clean_target = clean_target[1:-1]
        if clean_target.endswith((".qmd", ".html")):
            return match.group(0)

        source_path = (current_entry.source.parent / clean_target).resolve()
        try:
            relative_source = source_path.relative_to(project_root)
        except ValueError:
            return match.group(0)

        href = relative_href(current_entry.target, relative_source)
        wrapped = f"<{href}>" if " " in href else href
        return f"{label}({wrapped})"

    return pattern.sub(repl, markdown)


def relative_href(from_path: Path, to_path: Path) -> str:
    from_dir = from_path.parent
    rel = Path(
        *(
            Path(
                shutil.os.path.relpath(to_path.as_posix(), from_dir.as_posix())
            ).parts
        )
    )
    return rel.as_posix()


def note_front_matter(entry: Entry) -> str:
    return "\n".join(
        [
            "---",
            f'title: "{escape_quotes(entry.title)}"',
            "breadcrumbs: true",
            "---",
            "",
        ]
    )


def pdf_page(entry: Entry) -> str:
    pdf_href = relative_href(entry.target, entry.relative)
    source_href = pdf_href
    title = escape_quotes(entry.title)
    return "\n".join(
        [
            "---",
            f'title: "{title}"',
            "breadcrumbs: true",
            "---",
            "",
            f"[Open original PDF]({pdf_href})",
            "",
            f'<iframe class="pdf-frame" src="{html.escape(pdf_href)}"></iframe>',
            "",
            "::: {.source-links}",
            f"Source file: `{entry.relative.as_posix()}`  ",
            f"Download: [PDF]({source_href})",
            ":::",
            "",
        ]
    )


def escape_quotes(value: str) -> str:
    return value.replace('"', '\\"')


def write_note_pages(project_root: Path, entries: list[Entry], lookup: dict[str, list[Entry]]) -> None:
    for entry in entries:
        text = entry.source.read_text(encoding="utf-8", errors="ignore")
        text = strip_front_matter(text)
        text = replace_wikilinks(text, entry, lookup)
        text = rewrite_asset_links(text, entry, project_root)

        source_href = relative_href(entry.target, entry.relative)
        content = [
            note_front_matter(entry),
            text.rstrip(),
            "",
            "::: {.source-links}",
            f"Source file: `{entry.relative.as_posix()}`  ",
            f"Download raw note: [Markdown]({source_href})",
            ":::",
            "",
        ]

        output_path = project_root / entry.target
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(content), encoding="utf-8")


def write_pdf_pages(project_root: Path, entries: list[Entry]) -> None:
    for entry in entries:
        output_path = project_root / entry.target
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pdf_page(entry), encoding="utf-8")


def strip_front_matter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("\n")
    if len(parts) < 3:
        return text
    for index in range(1, len(parts)):
        if parts[index].strip() == "---":
            return "\n".join(parts[index + 1 :]).lstrip()
    return text


def write_site_data(project_root: Path, note_entries: list[Entry], pdf_entries: list[Entry]) -> None:
    subjects = sorted(set([entry.subject for entry in note_entries + pdf_entries]), key=str.lower)
    note_groups = grouped_subjects(note_entries)
    pdf_groups = grouped_subjects(pdf_entries)
    subject_payload = []

    for subject in subjects:
        subject_slug = slugify(subject)
        notes = note_groups.get(subject, [])
        pdfs = pdf_groups.get(subject, [])
        subject_payload.append(
            {
                "title": subject,
                "slug": subject_slug,
                "href": f"generated/subjects/{subject_slug}.qmd",
                "note_count": len(notes),
                "pdf_count": len(pdfs),
                "notes": [
                    {"title": entry.title, "href": entry.target.as_posix()}
                    for entry in notes
                ],
                "pdfs": [
                    {"title": entry.title, "href": entry.target.as_posix()}
                    for entry in pdfs
                ],
            }
        )

    payload = {
        "summary": {
            "subjects": len(subjects),
            "notes": len(note_entries),
            "pdfs": len(pdf_entries),
        },
        "subjects": subject_payload,
    }

    output_path = project_root / "generated" / "site-data.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_subject_pages(project_root: Path, note_entries: list[Entry], pdf_entries: list[Entry]) -> None:
    output_dir = project_root / "generated" / "subjects"
    output_dir.mkdir(parents=True, exist_ok=True)
    note_groups = grouped_subjects(note_entries)
    pdf_groups = grouped_subjects(pdf_entries)

    subjects = sorted(set([entry.subject for entry in note_entries + pdf_entries]), key=str.lower)
    for subject in subjects:
        lines = [
            "---",
            f'title: "{escape_quotes(subject)}"',
            "breadcrumbs: true",
            "---",
            "",
            f"## {subject}",
            "",
        ]

        notes = note_groups.get(subject, [])
        pdfs = pdf_groups.get(subject, [])

        lines.extend(
            [
                '<div class="quick-facts">',
                f'<div class="quick-fact"><strong>{len(notes)}</strong>Notes</div>',
                f'<div class="quick-fact"><strong>{len(pdfs)}</strong>PDFs</div>',
                "</div>",
                "",
            ]
        )

        if notes:
            lines.extend(["### Notes", ""])
            for entry in notes:
                lines.append(f"- [{entry.title}]({relative_href(Path('generated/subjects') / f'{slugify(subject)}.qmd', entry.target)})")
            lines.append("")

        if pdfs:
            lines.extend(["### PDFs", ""])
            for entry in pdfs:
                lines.append(f"- [{entry.title}]({relative_href(Path('generated/subjects') / f'{slugify(subject)}.qmd', entry.target)})")
            lines.append("")

        (output_dir / f"{slugify(subject)}.qmd").write_text("\n".join(lines), encoding="utf-8")


def clean_generated(project_root: Path) -> None:
    generated_dir = project_root / "generated"
    if generated_dir.exists():
        shutil.rmtree(generated_dir)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Quarto browse pages for IB notes.")
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to scan. Defaults to the current working directory.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(args.root).resolve()

    clean_generated(project_root)

    notes, pdfs, _assets = discover_files(project_root)
    note_entries, pdf_entries = build_entries(project_root, notes, pdfs)
    lookup = build_note_lookup(note_entries)

    write_note_pages(project_root, note_entries, lookup)
    write_pdf_pages(project_root, pdf_entries)
    write_subject_pages(project_root, note_entries, pdf_entries)
    write_site_data(project_root, note_entries, pdf_entries)

    print(
        f"Generated {len(note_entries)} note pages, {len(pdf_entries)} PDF pages, "
        f"and {len(set([entry.subject for entry in note_entries + pdf_entries]))} subject pages."
    )


if __name__ == "__main__":
    main()
