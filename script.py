import os
from PyPDF2 import PdfReader, PdfWriter

# Function to split the pages of a PDF into left and right halves
def split_pdf_pages(input_pdf_path, output_pdf_path):
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()

    for page in reader.pages:
        media_box = page.mediabox

        # Get the middle of the page (to split into left and right)
        mid_x = media_box.upper_right[0] / 2

        # Create left half of the page
        left_page = PdfWriter()
        left_page.add_page(page)
        left_page.pages[0].mediabox.upper_right = (mid_x, media_box.upper_right[1])

        # Create right half of the page
        right_page = PdfWriter()
        right_page.add_page(page)
        right_page.pages[0].mediabox.lower_left = (mid_x, media_box.lower_left[1])

        # Add the left and right pages to the writer
        writer.add_page(left_page.pages[0])
        writer.add_page(right_page.pages[0])

    # Write the output PDF
    with open(output_pdf_path, 'wb') as output_pdf:
        writer.write(output_pdf)

# Function to process PDFs in folder A and export to folder B
def process_pdfs(input_folder, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for filename in os.listdir(input_folder):
        if filename.endswith(".pdf"):
            input_pdf_path = os.path.join(input_folder, filename)
            output_pdf_path = os.path.join(output_folder, filename)
            print(f"Processing {filename}...")

            # Split the PDF pages
            split_pdf_pages(input_pdf_path, output_pdf_path)

            print(f"Saved split PDF to {output_pdf_path}")

if __name__ == "__main__":
    # Folder A contains the input PDFs, and Folder B will hold the output PDFs
    input_folder = "A"
    output_folder = "B"

    process_pdfs(input_folder, output_folder)
