import os
from PyPDF2 import PdfReader, PdfWriter

# Function to split each page of the PDF into two (left and right halves)
def split_pdf_pages(input_pdf_path, output_pdf_path):
    reader = PdfReader(input_pdf_path)
    writer = PdfWriter()

    # Loop through each page
    for i, page in enumerate(reader.pages):
        # Split left half
        left_page = page
        left_page.cropBox.lowerRight = (left_page.cropBox.getUpperRight_x() / 2, left_page.cropBox.getLowerLeft_y())
        writer.add_page(left_page)

        # Split right half
        right_page = page
        right_page.cropBox.lowerLeft = (right_page.cropBox.getUpperRight_x() / 2, right_page.cropBox.getLowerLeft_y())
        writer.add_page(right_page)

    # Save the result as a single output PDF
    with open(output_pdf_path, "wb") as output_pdf:
        writer.write(output_pdf)

    print(f"Processed {input_pdf_path}. Exported to {output_pdf_path}")

# Function to process all PDFs in the input folder
def process_pdfs(input_folder, output_folder):
    # Ensure the output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # Loop through all PDF files in the input folder
    for filename in os.listdir(input_folder):
        if filename.endswith(".pdf"):
            input_pdf_path = os.path.join(input_folder, filename)
            output_pdf_path = os.path.join(output_folder, filename)  # Same filename for the output
            split_pdf_pages(input_pdf_path, output_pdf_path)

# Main function to run the script
if __name__ == "__main__":
    input_folder = 'A'  # Folder where original PDFs are stored
    output_folder = 'B'  # Folder to save the split PDFs

    # Process all PDFs in folder A and export to folder B
    process_pdfs(input_folder, output_folder)
