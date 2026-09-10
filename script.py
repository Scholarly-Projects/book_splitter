import os

from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

INPUT_FOLDER = "A"
OUTPUT_FOLDER = "B"


def _half_box(box, side):
    """Return a RectangleObject for the left or right half of `box`."""
    llx, lly = float(box.left), float(box.bottom)
    urx, ury = float(box.right), float(box.top)
    mid_x = (llx + urx) / 2
    return RectangleObject((llx, lly, mid_x, ury) if side == "left" else (mid_x, lly, urx, ury))


def split_pdf_pages(input_pdf_path, output_pdf_path):
    """Split every spread in a PDF into a left page followed by a right page."""
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()

    for page in reader.pages:
        # page.cropbox (falls back to mediabox if unset) is the box that
        # actually governs what's visible/rendered. Splitting on mediabox
        # instead would miss the true center whenever a PDF already has a
        # cropbox narrower than its mediabox (e.g. scanner-bed margin left
        # over from a prior crop), cutting off-center through the text.
        source_box = page.cropbox

        for side in ("left", "right"):
            half = writer.add_page(page)  # independent clone each call
            half_box = _half_box(source_box, side)
            half.mediabox = half_box
            half.cropbox = half_box

    with open(output_pdf_path, "wb") as output_pdf:
        writer.write(output_pdf)


def process_pdfs(input_folder, output_folder):
    """Split every PDF in input_folder and save results to output_folder."""
    if not os.path.isdir(input_folder):
        raise FileNotFoundError(f"Input folder not found: {input_folder}")

    os.makedirs(output_folder, exist_ok=True)

    pdf_files = sorted(f for f in os.listdir(input_folder) if f.lower().endswith(".pdf"))

    if not pdf_files:
        print(f"No PDF files found in '{input_folder}'.")
        return

    for filename in pdf_files:
        input_pdf_path = os.path.join(input_folder, filename)
        output_pdf_path = os.path.join(output_folder, filename)

        if os.path.exists(output_pdf_path):
            print(f"Skipping {filename} (already exists in '{output_folder}').")
            continue

        print(f"Processing {filename}...")
        try:
            split_pdf_pages(input_pdf_path, output_pdf_path)
            print(f"  Saved split PDF to {output_pdf_path}")
        except Exception as e:
            print(f"  Skipped {filename}: {e}")


if __name__ == "__main__":
    process_pdfs(INPUT_FOLDER, OUTPUT_FOLDER)