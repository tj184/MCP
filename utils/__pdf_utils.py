
import base64
import binascii
import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGES = 10
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000


def create_pdf(images_base64: list[str]) -> bytes:
    if not 1 <= len(images_base64) <= MAX_IMAGES:
        raise ValueError("Provide between 1 and 10 images.")

    pages = []

    try:
        for encoded in images_base64:
            if not isinstance(encoded, str):
                raise ValueError("Each image must be a base64 string.")

            if encoded.startswith("data:"):
                encoded = encoded.split(",", 1)[-1]

            if len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 16):
                raise ValueError("Image exceeds 5 MB.")

            try:
                image_bytes = base64.b64decode(
                    encoded, validate=True
                )
            except (binascii.Error, ValueError):
                raise ValueError("Invalid base64 image.")

            if len(image_bytes) > MAX_IMAGE_BYTES:
                raise ValueError("Image exceeds 5 MB.")

            try:
                with Image.open(io.BytesIO(image_bytes)) as img:
                    if img.width * img.height > MAX_PIXELS:
                        raise ValueError("Image dimensions too large.")

                    img.load()
                    page = ImageOps.exif_transpose(img).convert("RGB")
                    pages.append(page)

            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError("Invalid image file.") from exc

        output = io.BytesIO()

        pages[0].save(
            output,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=100.0,
        )

        return output.getvalue()

    finally:
        for page in pages:
            page.close()
