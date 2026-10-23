
import base64

from utils.pdf_utils import create_pdf


def images_to_pdf(images_base64: list[str]) -> dict:
    """
    Convert 1-10 base64 images into one PDF.
    Images are processed in the supplied order.
    """
    pdf_bytes = create_pdf(images_base64)

    return {
        "filename": "converted.pdf",
        "mime_type": "application/pdf",
        "size_bytes": len(pdf_bytes),
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
    }
