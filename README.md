# pdf-splitter

A simple Python script for splitting PDF into chapters.

## Modes:
1) Auto from PDF bookmarks / outlines
2) Manual from a JSON file with page ranges

---

## Requirements:
    `pip install pypdf`

---

## Examples:
    `python split_pdf_chapters.py --input book.pdf --output-dir chapters --from-bookmarks`
    `python split_pdf_chapters.py --input book.pdf --output-dir chapters --ranges chapters.json`

---

## Manual ranges JSON format:
`[
  {"title": "Chapter 1 - Introduction", "start": 1, "end": 18},
  {"title": "Chapter 2 - Linear Algebra", "start": 19, "end": 34}
]`

# Notes:
- Page numbers in the JSON file are 1-based and inclusive.
- For bookmarks mode, the script uses the selected bookmark level and splits from each
  bookmark start page to the page before the next bookmark.
