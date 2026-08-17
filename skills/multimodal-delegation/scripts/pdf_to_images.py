"""Convert PDF pages to PNG images for multimodal look_at analysis.

The look_at tool's backend (OpenAI-compatible) does not accept raw
`application/pdf` file parts — PDFs must be rasterized to images first.
This script renders each page to a PNG at 2x scale so the multimodal
model (qwen-3.7-plus) can read the content via `look_at`.

Usage:
    python pdf_to_images.py <input.pdf> [--outdir DIR] [--dpi 144] [--max-pages N]

Output:
    Writes `<outdir>/<basename>_page_1.png`, `..._page_2.png`, ... and prints
    the list of output paths to stdout (one per line), for piping into look_at.
"""
import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", help="Path to the input PDF file")
    parser.add_argument("--outdir", default=None, help="Output directory (default: alongside the PDF)")
    parser.add_argument("--dpi", type=int, default=144, help="Render resolution in DPI (default 144, ~2x)")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit number of pages (0 = all)")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    try:
        import pymupdf  # noqa: F401  (pymupdf exposes `fitz`-compatible API)
        import fitz
    except ImportError:
        print(
            "Error: pymupdf is not installed. Run: python -m pip install pymupdf",
            file=sys.stderr,
        )
        return 1

    outdir = Path(args.outdir) if args.outdir else pdf_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    total = doc.page_count
    page_count = total if args.max_pages <= 0 else min(args.max_pages, total)

    # scale factor: 72 DPI is the PDF internal unit; dpi/72 = zoom
    zoom = args.dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)

    outputs = []
    for i in range(page_count):
        page = doc.load_page(i)
        pix = page.get_pixmap(matrix=matrix)
        out = outdir / f"{pdf_path.stem}_page_{i + 1}.png"
        pix.save(str(out))
        outputs.append(str(out))

    doc.close()

    for path in outputs:
        print(path)
    print(
        f"# Rendered {page_count}/{total} pages from {pdf_path.name} at {args.dpi} DPI",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
