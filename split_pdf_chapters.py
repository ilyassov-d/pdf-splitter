"""
Split a PDF into chapter files.

Modes:
1) Auto from PDF bookmarks / outlines
2) Manual from a JSON file with page ranges

Requirements:
    pip install pypdf

Examples:
    python split_pdf_chapters.py --input book.pdf --output-dir chapters --from-bookmarks
    python split_pdf_chapters.py --input book.pdf --output-dir chapters --ranges chapters.json

Manual ranges JSON format:
[
  {"title": "Chapter 1 - Introduction", "start": 1, "end": 18},
  {"title": "Chapter 2 - Linear Algebra", "start": 19, "end": 34}
]

Notes:
- Page numbers in the JSON file are 1-based and inclusive.
- For bookmarks mode, the script uses the selected bookmark level and splits from each
  bookmark start page to the page before the next bookmark.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional

from pypdf import PdfReader, PdfWriter


@dataclass
class ChapterRange:
    title: str
    start: int  # 1-based inclusive
    end: int    # 1-based inclusive


def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" ._")
    if not name:
        name = "untitled"
    return name[:max_len]


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def write_chapter(reader: PdfReader, chapter: ChapterRange, output_dir: Path) -> Path:
    total_pages = len(reader.pages)
    if not (1 <= chapter.start <= total_pages):
        raise ValueError(f"Start page out of range for '{chapter.title}': {chapter.start}")
    if not (1 <= chapter.end <= total_pages):
        raise ValueError(f"End page out of range for '{chapter.title}': {chapter.end}")
    if chapter.end < chapter.start:
        raise ValueError(
            f"End page before start page for '{chapter.title}': {chapter.start}..{chapter.end}"
        )

    writer = PdfWriter()
    for i in range(chapter.start - 1, chapter.end):
        writer.add_page(reader.pages[i])

    safe = sanitize_filename(chapter.title)
    output_path = ensure_unique_path(output_dir / f"{safe}.pdf")
    with output_path.open("wb") as f:
        writer.write(f)
    return output_path


def load_manual_ranges(path: Path) -> List[ChapterRange]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Ranges JSON must be a list of objects.")

    chapters: List[ChapterRange] = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Entry #{idx} is not an object.")
        title = str(item.get("title", "")).strip()
        start = item.get("start")
        end = item.get("end")
        if not title:
            raise ValueError(f"Entry #{idx} is missing a non-empty 'title'.")
        if not isinstance(start, int) or not isinstance(end, int):
            raise ValueError(f"Entry #{idx} must have integer 'start' and 'end' values.")
        chapters.append(ChapterRange(title=title, start=start, end=end))
    return chapters


def iter_outline_entries(outline: Any, level: int = 1) -> Iterable[tuple[int, Any]]:
    """
    Flatten pypdf outline structure recursively.
    Yields (level, destination_like_object).
    """
    if isinstance(outline, list):
        for item in outline:
            yield from iter_outline_entries(item, level)
    else:
        yield (level, outline)



def extract_bookmark_chapters(reader: PdfReader, target_level: int = 1) -> List[ChapterRange]:
    """
    Create chapter ranges from bookmarks of a given outline level.
    Splits from each bookmark page to the page before the next bookmark.
    """
    total_pages = len(reader.pages)

    try:
        raw_outline = reader.outline
    except Exception:
        try:
            raw_outline = reader.outlines
        except Exception as e:
            raise RuntimeError("Could not read PDF bookmarks/outlines.") from e

    entries: List[tuple[str, int]] = []
    current_level = 0

    def walk(nodes: Any, level: int = 1) -> None:
        nonlocal entries
        if isinstance(nodes, list):
            prev_was_entry = False
            for item in nodes:
                if isinstance(item, list):
                    # Child list belongs to the most recent entry, therefore level+1
                    walk(item, level + 1)
                    prev_was_entry = False
                else:
                    try:
                        title = str(getattr(item, "title", str(item))).strip()
                    except Exception:
                        title = "Untitled"
                    try:
                        page_index = reader.get_destination_page_number(item)
                    except Exception:
                        try:
                            page_index = reader.get_page_number(item.page)
                        except Exception:
                            continue
                    if level == target_level:
                        entries.append((title or f"Chapter_{len(entries)+1}", page_index + 1))
                    prev_was_entry = True
        else:
            # Rare single-node case
            try:
                title = str(getattr(nodes, "title", str(nodes))).strip()
                page_index = reader.get_destination_page_number(nodes)
                if level == target_level:
                    entries.append((title or f"Chapter_{len(entries)+1}", page_index + 1))
            except Exception:
                pass

    walk(raw_outline, level=1)

    # Deduplicate bookmarks that resolve to the same start page and title
    cleaned: List[tuple[str, int]] = []
    seen = set()
    for title, start in entries:
        key = (title, start)
        if key not in seen:
            seen.add(key)
            cleaned.append((title, start))

    cleaned.sort(key=lambda x: x[1])

    if not cleaned:
        raise ValueError(
            f"No bookmarks found at outline level {target_level}. "
            f"Try another --bookmark-level or use --ranges."
        )

    chapters: List[ChapterRange] = []
    for i, (title, start) in enumerate(cleaned):
        end = cleaned[i + 1][1] - 1 if i + 1 < len(cleaned) else total_pages
        if 1 <= start <= end <= total_pages:
            chapters.append(ChapterRange(title=title, start=start, end=end))

    if not chapters:
        raise ValueError("Bookmarks were found, but no valid page ranges could be constructed.")
    return chapters


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Split a PDF into chapter files using bookmarks or manual page ranges."
    )
    parser.add_argument("--input", required=True, help="Path to input PDF file.")
    parser.add_argument("--output-dir", required=True, help="Directory for split chapter PDFs.")

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--from-bookmarks",
        action="store_true",
        help="Split using PDF bookmarks/outlines."
    )
    mode.add_argument(
        "--ranges",
        help="Path to JSON file with manual chapter page ranges."
    )

    parser.add_argument(
        "--bookmark-level",
        type=int,
        default=1,
        help="Outline level to use when splitting from bookmarks (default: 1)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show detected chapter ranges without writing files."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_dir = Path(args.output_dir)

    if not input_path.exists():
        print(f"Error: input PDF not found: {input_path}", file=sys.stderr)
        return 1
    if input_path.suffix.lower() != ".pdf":
        print("Error: input file must be a PDF.", file=sys.stderr)
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        reader = PdfReader(str(input_path))
    except Exception as e:
        print(f"Error: failed to open PDF: {e}", file=sys.stderr)
        return 1

    try:
        if args.from_bookmarks:
            chapters = extract_bookmark_chapters(reader, target_level=args.bookmark_level)
        else:
            chapters = load_manual_ranges(Path(args.ranges))
    except Exception as e:
        print(f"Error: failed to build chapter ranges: {e}", file=sys.stderr)
        return 1

    print(f"Input: {input_path}")
    print(f"Total pages: {len(reader.pages)}")
    print("Chapters:")
    for ch in chapters:
        print(f"  - {ch.title} | pages {ch.start}-{ch.end}")

    if args.dry_run:
        print("\nDry run complete. No files written.")
        return 0

    written = []
    try:
        for ch in chapters:
            path = write_chapter(reader, ch, output_dir)
            written.append(path)
    except Exception as e:
        print(f"Error while writing chapter PDFs: {e}", file=sys.stderr)
        return 1

    print("\nWritten files:")
    for path in written:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())