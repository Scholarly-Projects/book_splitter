#!/usr/bin/env python3
"""
Book Splitter
"""

import os
import re
import sys
import logging
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageFilter

import pymupdf as fitz   # PyMuPDF; the module is named "fitz" in the OCR tool

# ---------------- Configuration ----------------
INPUT_FOLDER  = "A"
OUTPUT_FOLDER = "B"
SKIP_EXISTING_OUTPUT = True

# ---- Spread detection ----
SPREAD_MODE        = "auto"        # "auto": detect; "always": split every page at its spine; "never": split nothing
SPREAD_MIN_ASPECT  = 1.15          # width / height at or above which a page *may* be a spread
GUTTER_SEARCH_BAND = (0.35, 0.65)  # fraction of the page width searched for the spine
VERIFY_SPREADS     = True          # keep wide pages whole unless a spine is actually found
ANALYSIS_WIDTH_PX  = 1200          # pages are rendered about this wide for analysis

# Per-page thresholds (grey levels 0-255 / ratios).
SHADOW_MIN_DEPTH   = 10.0   # gutter at least this much darker than the open page = shadow/crease
CHANNEL_MAX_RATIO  = 0.45   # text in the gutter band at most this fraction of the text on either side
CONTENT_MIN_STD    = 4.0    # a half page with less variation than this counts as blank

# ---- Whole-document check ----
DOCUMENT_CONSISTENCY   = True
CONSISTENCY_MIN_SPREADS = 3     # clear spreads needed before the document check is used
CONSISTENCY_MIN_SHARE   = 0.5   # ...and at least this share of the wide pages must be clear spreads
ASPECT_TOLERANCE        = 0.10  # wide pages within 10% of the spreads' shape count as spreads
GUTTER_MAX_DEVIATION    = 0.05  # spine more than 5% of the width from the usual position is re-searched

# ---- Output check ----
VERIFY_OUTPUT = True   # render every half and compare it with the source strip

# Per-file overrides (1-based page numbers), e.g. {"book.pdf": {"split": [3], "keep": [1, 120]}}
PAGE_OVERRIDES: dict = {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------- Image helpers (from Opticolumn Book Scan) ----------------
def flatten_illumination(gray: Image.Image) -> Image.Image:
    """
    Remove gutter shadow and uneven lighting: estimate the paper brightness
    with a max filter (wipes out the text) plus a heavy blur on a small copy,
    then divide the image by it.
    """
    w, h = gray.size
    scale = max(1, int(round(max(w, h) / 800)))
    small = gray.resize((max(1, w // scale), max(1, h // scale)), Image.BILINEAR)
    bg = small.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(radius=15))
    bg = bg.resize((w, h), Image.BILINEAR)
    g = np.asarray(gray, dtype=np.float32)
    b = np.maximum(np.asarray(bg, dtype=np.float32), 1.0)
    out = np.clip(g / b * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(out, "L")


def render_gray(page: "fitz.Page", target_width: int = ANALYSIS_WIDTH_PX,
                clip: Optional["fitz.Rect"] = None) -> np.ndarray:
    """Render the visible page (or *clip* of it) as a greyscale array."""
    width = (clip or page.rect).width
    zoom = target_width / max(1.0, width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY,
                          alpha=False, clip=clip)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


# ---------------- Spine detection ----------------
@dataclass
class PageDecision:
    split: bool
    gutter_frac: Optional[float]   # spine position as a fraction of the visible width
    reason: str
    aspect: float = 0.0
    kind: str = ""                 # narrow | shadow | channel | one_side | across | override | ...
    info: Dict[str, float] = field(default_factory=dict)


def find_gutter(arr: np.ndarray, band: Tuple[float, float] = GUTTER_SEARCH_BAND) -> Tuple[float, dict]:
    """
    Locate the spine of a (possible) two-page spread within *band* (fractions
    of the width).  Returns the spine as a fraction of the width, plus the
    measurements used to verify it.
    """
    H, W = arr.shape
    raw = arr.astype(np.float32)
    flat = np.asarray(flatten_illumination(Image.fromarray(arr, "L")), dtype=np.float32)
    y0, y1 = int(H * 0.05), max(int(H * 0.95), int(H * 0.05) + 1)
    lo, hi = int(W * max(0.0, band[0])), int(W * min(1.0, band[1]))
    if hi - lo < 5:
        return 0.5, {}

    # Text makes a column vary top to bottom (lines and gaps); a gutter
    # shadow or crease is roughly uniform, so the per-column standard
    # deviation separates them where an ink count would not.
    ink = flat[y0:y1].std(axis=0)
    wide = max(3, int(W * 0.03)) | 1
    ink_s = np.convolve(ink, np.ones(wide) / wide, mode="same")
    ink_w = ink_s[lo:hi]

    # Paper brightness per column (90th percentile, so text doesn't count).
    # It only drops for something dark down nearly the full height of the
    # page: a gutter shadow or crease, not a photo or a heading.
    paper = np.convolve(np.percentile(raw[y0:y1], 90, axis=0), np.ones(5) / 5, mode="same")
    near, far = int(W * 0.04), int(W * 0.10)
    m = max(1, int(W * 0.03))

    def shadow_depth_at(x: int) -> float:
        """How much darker the paper is at x than the open paper on *both* sides.
        A page edge against a dark scanner bed is dark on one side only."""
        l_ref = paper[max(0, x - far):max(1, x - near)]
        r_ref = paper[min(W - 1, x + near):min(W, x + far)]
        if not (l_ref.size and r_ref.size):
            return 0.0
        band_ = paper[max(0, x - m // 2):min(W, x + m // 2 + 1)]
        return min(float(np.median(l_ref)), float(np.median(r_ref))) - float(band_.min())

    # 1) A clear gutter shadow/crease in the search band wins outright.
    sx = lo + int(np.argmin(paper[lo:hi]))
    if shadow_depth_at(sx) >= SHADOW_MIN_DEPTH:
        gx = sx
    else:
        # 2) Otherwise the middle of the widest text-free channel (with the
        #    darkest column inside it, if there is a faint shadow).
        i_min = int(np.argmin(ink_w))
        floor_, med = float(ink_w.min()), float(np.median(ink_w))
        limit = floor_ + 0.3 * max(med - floor_, 0.0)
        a = b = i_min
        while a > 0 and ink_w[a - 1] <= limit:
            a -= 1
        while b < len(ink_w) - 1 and ink_w[b + 1] <= limit:
            b += 1
        # Darkest *paper* in the channel (a faint shadow); column averages
        # would be pulled toward text at the channel's edges.
        run = paper[lo:hi][a:b + 1]
        x = a + int(np.argmin(run)) if run.max() - run.min() >= 4 else (a + b) // 2
        gx = lo + x
    gx = int(min(max(gx, 1), W - 1))

    # Measurements for verification.  The text-bearing parts of each side
    # are taken from the outer 5%..(gutter - 3%) so neither the book edge
    # nor the gutter itself is counted as text.
    edge = int(W * 0.05)
    left_ink = ink_s[edge:max(edge + 1, gx - m)]
    right_ink = ink_s[min(gx + m, W - edge - 1):W - edge]
    gband = slice(max(0, gx - m // 2), min(W, gx + m // 2 + 1))
    info = {
        "gutter_ink":   float(ink_s[gband].mean()),
        "left_ink":     float(np.percentile(left_ink, 75)) if left_ink.size else 0.0,
        "right_ink":    float(np.percentile(right_ink, 75)) if right_ink.size else 0.0,
        "shadow_depth": shadow_depth_at(gx),
    }
    return gx / W, info


def _detail(d: PageDecision) -> str:
    i = d.info
    if not i:
        return f"aspect {d.aspect:.2f}"
    return (f"aspect {d.aspect:.2f}, shadow {i['shadow_depth']:.0f}, "
            f"text L/gutter/R {i['left_ink']:.1f}/{i['gutter_ink']:.1f}/{i['right_ink']:.1f}")


def analyse_page(page: "fitz.Page") -> PageDecision:
    """Decide on its own whether one PDF page is a spread, and where its spine is."""
    r = page.rect
    aspect = r.width / max(1e-6, r.height)

    if SPREAD_MODE == "never":
        return PageDecision(False, None, "splitting disabled", aspect, "disabled")
    if SPREAD_MODE == "auto" and aspect < SPREAD_MIN_ASPECT:
        return PageDecision(False, None, "single page", aspect, "narrow")

    frac, info = find_gutter(render_gray(page))
    d = PageDecision(False, frac, "", aspect, "", info)
    if SPREAD_MODE == "always" or not VERIFY_SPREADS or not info:
        d.split, d.kind, d.reason = True, "unverified", "spread (unverified)"
        return d

    left_has = info["left_ink"] >= CONTENT_MIN_STD
    right_has = info["right_ink"] >= CONTENT_MIN_STD
    if info["shadow_depth"] >= SHADOW_MIN_DEPTH and (left_has or right_has):
        d.split, d.kind, d.reason = True, "shadow", "spread, gutter shadow"
    elif (left_has and right_has and
          info["gutter_ink"] <= CHANNEL_MAX_RATIO * min(info["left_ink"], info["right_ink"])):
        d.split, d.kind, d.reason = True, "channel", "spread, text-free channel"
    elif not (left_has and right_has):
        d.kind, d.reason = "one_side", "wide single page, content on one side only"
    else:
        d.kind, d.reason = "across", "wide single page, content runs across the middle"
    return d


def apply_document_consistency(doc: "fitz.Document", decisions: List[PageDecision]) -> None:
    """
    Use the document as a whole to settle doubtful pages.  If most wide pages
    are clear spreads, then (a) wide pages of the same shape whose gutter was
    too faint to confirm on its own are spreads as well, and (b) any spine
    found far from the usual position is searched for again near it.
    """
    if not DOCUMENT_CONSISTENCY or SPREAD_MODE != "auto":
        return
    wide = [d for d in decisions if d.kind not in ("narrow", "disabled", "override_keep")]
    clear = [d for d in wide if d.split and d.kind in ("shadow", "channel")]
    if len(clear) < CONSISTENCY_MIN_SPREADS or len(clear) < CONSISTENCY_MIN_SHARE * len(wide):
        return

    usual_aspect = median(d.aspect for d in clear)
    # The usual spine position comes from spines near the middle, so a few
    # strays don't pull it off.
    central = [d.gutter_frac for d in clear if abs(d.gutter_frac - 0.5) <= 0.08] or \
              [d.gutter_frac for d in clear]
    usual_gutter = median(central)
    window = (usual_gutter - GUTTER_MAX_DEVIATION, usual_gutter + GUTTER_MAX_DEVIATION)
    logger.info(f"  Document check: {len(clear)}/{len(wide)} wide pages are clear spreads; "
                f"usual shape {usual_aspect:.2f}, usual spine {usual_gutter:.1%}")

    for i, d in enumerate(decisions):
        if d.kind == "across" and abs(d.aspect / usual_aspect - 1) <= ASPECT_TOLERANCE:
            frac, info = find_gutter(render_gray(doc[i]), window)
            d.split, d.gutter_frac, d.info = True, frac, info
            d.kind, d.reason = "consistent", "spread, same shape as the other spreads (faint gutter)"
        elif d.split and d.kind in ("shadow", "channel") and \
                abs(d.gutter_frac - usual_gutter) > GUTTER_MAX_DEVIATION:
            old = d.gutter_frac
            frac, info = find_gutter(render_gray(doc[i]), window)
            d.gutter_frac, d.info = frac, info
            d.reason += f"; spine at {old:.1%} was far from the usual position, re-searched near it"


# ---------------- Page boxes ----------------
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)")


def _box_value(doc: "fitz.Document", xref: int, key: str) -> Optional[List[float]]:
    """Box array for *key* on object *xref*, following page-tree inheritance."""
    seen = set()
    while xref and xref not in seen:
        seen.add(xref)
        typ, val = doc.xref_get_key(xref, key)
        if typ == "xref":                                  # box stored as its own object
            val, typ = doc.xref_object(int(val.split()[0])), "array"
        if typ == "array":
            nums = [float(n) for n in _NUM.findall(val)]
            if len(nums) == 4:
                x0, y0, x1, y1 = nums
                return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]
        typ, val = doc.xref_get_key(xref, "Parent")
        xref = int(val.split()[0]) if typ == "xref" else 0
    return None


def _visible_box_pdf(doc: "fitz.Document", page: "fitz.Page") -> List[float]:
    """The page's visible area (CropBox within MediaBox) in PDF user space."""
    mb = _box_value(doc, page.xref, "MediaBox") or [0.0, 0.0, 612.0, 792.0]
    cb = _box_value(doc, page.xref, "CropBox") or mb
    box = [max(mb[0], cb[0]), max(mb[1], cb[1]), min(mb[2], cb[2]), min(mb[3], cb[3])]
    if box[2] <= box[0] or box[3] <= box[1]:
        box = mb
    return box


def _strip_to_pdf_box(doc: "fitz.Document", page: "fitz.Page", x0: float, x1: float) -> List[float]:
    """
    Convert a vertical strip [x0, x1] of the *visible* page (as rendered:
    CropBox applied, rotation applied) into a PDF box [llx lly urx ury].
    Works from the PDF's own boxes, so the result doesn't depend on how a
    PyMuPDF version reports page.cropbox / page.mediabox.
    """
    vx0, vy0, vx1, vy1 = _visible_box_pdf(doc, page)
    # visible -> unrotated, measured from the visible area's top-left corner
    strip = fitz.Rect(x0, 0, x1, page.rect.height) * page.derotation_matrix
    strip.normalize()
    llx, urx = vx0 + strip.x0, vx0 + strip.x1
    lly, ury = vy1 - strip.y1, vy1 - strip.y0
    # Whole points (1/72 in) keep render pixel grids aligned; stay inside the page.
    box = [round(llx), round(lly), round(urx), round(ury)]
    box = [max(vx0, box[0]), max(vy0, box[1]), min(vx1, box[2]), min(vy1, box[3])]
    return [float(v) for v in box]


def _set_page_box(doc: "fitz.Document", page: "fitz.Page", box: List[float]) -> None:
    """Make *box* both the MediaBox and CropBox; drop boxes that might now overhang it."""
    arr = "[{:g} {:g} {:g} {:g}]".format(*box)
    doc.xref_set_key(page.xref, "MediaBox", arr)
    doc.xref_set_key(page.xref, "CropBox", arr)
    for key in ("TrimBox", "BleedBox", "ArtBox"):
        doc.xref_set_key(page.xref, key, "null")


def _check_half(src_page: "fitz.Page", x0: float, x1: float, half: "fitz.Page") -> Tuple[bool, str]:
    """Render the new half and the same strip of the source; they must match."""
    strip = fitz.Rect(x0, 0, x1, src_page.rect.height)
    a = render_gray(src_page, 300, clip=strip).astype(np.float32)
    b = render_gray(half, 300).astype(np.float32)
    if abs(a.shape[0] - b.shape[0]) > 3 or abs(a.shape[1] - b.shape[1]) > 3:
        return False, f"size {b.shape[1]}x{b.shape[0]} px, expected {a.shape[1]}x{a.shape[0]}"
    h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
    diff = float(np.abs(a[:h, :w] - b[:h, :w]).mean())
    limit = max(6.0, 0.35 * float(a.std()))
    return diff <= limit, f"mean difference {diff:.1f} (limit {limit:.1f})"


# ---------------- PDF processing ----------------
def split_pdf_pages(input_pdf_path: str, output_pdf_path: str) -> Tuple[int, int]:
    """
    Write a copy of *input_pdf_path* in which every spread becomes a left
    page followed by a right page and every single page appears once,
    unchanged.  Returns (spreads split, single pages kept).
    """
    name = os.path.basename(input_pdf_path)
    overrides = PAGE_OVERRIDES.get(name, {})
    force_split, force_keep = set(overrides.get("split", [])), set(overrides.get("keep", []))

    n_split = n_single = 0
    with fitz.open(input_pdf_path) as src, fitz.open() as out:
        if src.needs_pass:
            raise ValueError("PDF is password protected")

        # Pass 1: each page on its own.
        decisions: List[PageDecision] = []
        for i, page in enumerate(src):
            pno = i + 1
            if pno in force_keep:
                d = PageDecision(False, None, "kept whole (override)", 0.0, "override_keep")
            else:
                d = analyse_page(page)
            decisions.append(d)

        # Pass 2: the document as a whole.
        apply_document_consistency(src, decisions)

        for i, d in enumerate(decisions):
            if (i + 1) in force_split and not d.split:
                frac, info = find_gutter(render_gray(src[i]))
                d.split, d.gutter_frac, d.info = True, frac, info
                d.kind, d.reason = "override", "spread (override)"

        # Build the output.
        page_map = {}   # source page number -> output page number (1-based)
        for i, (page, d) in enumerate(zip(src, decisions)):
            pno = i + 1
            page_map[pno] = len(out) + 1

            if not d.split:
                out.insert_pdf(src, from_page=i, to_page=i)   # single page: once, untouched
                n_single += 1
                logger.info(f"  p{pno}: {d.reason} ({_detail(d)}) -> kept whole")
                continue

            gx = d.gutter_frac * page.rect.width
            for side, x0, x1 in (("left", 0.0, gx), ("right", gx, page.rect.width)):
                # Each insert_pdf call makes a new page object, so the two
                # halves never share a box.
                out.insert_pdf(src, from_page=i, to_page=i)
                half = out[-1]
                _set_page_box(out, half, _strip_to_pdf_box(src, page, x0, x1))
                if VERIFY_OUTPUT:
                    half = out.reload_page(half)
                    ok, msg = _check_half(page, x0, x1, half)
                    if not ok:
                        raise RuntimeError(f"p{pno} {side} half does not match the source ({msg}); "
                                           f"nothing written for this file")
            n_split += 1
            logger.info(f"  p{pno}: {d.reason} ({_detail(d)}) -> split at {d.gutter_frac:.1%}")

        expected = n_single + 2 * n_split
        if len(out) != expected:
            raise RuntimeError(f"output has {len(out)} pages, expected {expected}")

        if src.metadata:
            out.set_metadata({k: v for k, v in src.metadata.items()
                              if v and k not in ("format", "encryption")})
        # Carry bookmarks over, pointing at the new page numbers.
        toc = src.get_toc(simple=True)
        if toc:
            try:
                out.set_toc([[lvl, title, page_map.get(pg, pg)] for lvl, title, pg in toc])
            except Exception as e:
                logger.warning(f"  Bookmarks not copied: {e}")

        # Write to a temporary file first so an interrupted run never leaves
        # a partial output that SKIP_EXISTING_OUTPUT would then skip.
        tmp = output_pdf_path + ".part"
        out.save(tmp, garbage=4, deflate=True, deflate_images=False)  # garbage=4 merges the image each half shares
    os.replace(tmp, output_pdf_path)
    return n_split, n_single


def process_pdfs(input_folder: str, output_folder: str) -> None:
    """Split every PDF in input_folder and save results to output_folder."""
    in_dir, out_dir = Path(input_folder), Path(output_folder)
    if not in_dir.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_folder}")
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(p for p in in_dir.iterdir() if p.suffix.lower() == ".pdf")
    if not pdf_files:
        logger.info(f"No PDF files found in '{input_folder}'.")
        return

    summary = []
    for pdf in pdf_files:
        target = out_dir / pdf.name
        if SKIP_EXISTING_OUTPUT and target.exists():
            logger.info(f"Skipping {pdf.name} (already exists in '{output_folder}').")
            summary.append((pdf.name, "SKIPPED", ""))
            continue
        logger.info(f"Processing {pdf.name}...")
        try:
            n_split, n_single = split_pdf_pages(str(pdf), str(target))
            msg = f"{n_split} spreads split, {n_single} single pages kept -> {n_single + 2 * n_split} pages"
            logger.info(f"  Saved {target}: {msg}")
            summary.append((pdf.name, "OK", msg))
        except Exception as e:
            logger.error(f"  Failed {pdf.name}: {e}")
            Path(str(target) + ".part").unlink(missing_ok=True)
            summary.append((pdf.name, "FAILED", str(e)))

    logger.info("SUMMARY")
    for name, status, msg in summary:
        logger.info(f"  {status:<8} {name}  {msg}")


if __name__ == "__main__":
    try:
        process_pdfs(INPUT_FOLDER, OUTPUT_FOLDER)
    except FileNotFoundError as e:
        logger.error(e)
        sys.exit(1)