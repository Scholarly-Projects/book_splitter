import os
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject


def split_pdf_pages(input_pdf_path, output_pdf_path):
    """Split every page of one PDF into left and right halves."""
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()

    for page in reader.pages:
        box = page.mediabox
        llx, lly = float(box.left), float(box.bottom)
        urx, ury = float(box.right), float(box.top)
        mid_x = (llx + urx) / 2  # true center, works for any origin

        # Left half: add the page, then give this copy its own,
        # independent MediaBox/CropBox (a new object, not a mutated
        # shared one).
        left = writer.add_page(page)
        left.mediabox = RectangleObject((llx, lly, mid_x, ury))
        left.cropbox = RectangleObject((llx, lly, mid_x, ury))

        # Right half: add the still-untouched source page again, then
        # give this copy its own independent MediaBox/CropBox.
        right = writer.add_page(page)
        right.mediabox = RectangleObject((mid_x, lly, urx, ury))
        right.cropbox = RectangleObject((mid_x, lly, urx, ury))

    with open(output_pdf_path, "wb") as output_pdf:
        writer.write(output_pdf)


def process_pdfs(input_folder, output_folder):
    """Process every PDF in input_folder and save split versions to output_folder."""
    if not os.path.isdir(input_folder):
        raise FileNotFoundError(f"Input folder not found: {input_folder}")

    os.makedirs(output_folder, exist_ok=True)

    pdf_files = sorted(
        f for f in os.listdir(input_folder) if f.lower().endswith(".pdf")
    )

    if not pdf_files:
        print(f"No PDF files found in '{input_folder}'.")
        return

    for filename in pdf_files:
        input_pdf_path = os.path.join(input_folder, filename)
        output_pdf_path = os.path.join(output_folder, filename)
        print(f"Processing {filename}...")
        try:
            split_pdf_pages(input_pdf_path, output_pdf_path)
            print(f"Saved split PDF to {output_pdf_path}")
        except Exception as e:
            print(f"  Skipped {filename}: {e}")


if __name__ == "__main__":
    # Folder A contains the input PDFs, and Folder B will hold the output PDFs
    input_folder = "A"
    output_folder = "B"
    process_pdfs(input_folder, output_folder)