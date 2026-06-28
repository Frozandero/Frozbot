import io
import importlib.util
import unittest


@unittest.skipUnless(
    importlib.util.find_spec("PIL") is not None,
    "Pillow is required for attachment validation tests",
)
class AttachmentValidationTests(unittest.TestCase):
    def setUp(self):
        import config

        self.config = config
        self.old_max_bytes = config.MAX_IMAGE_ATTACHMENT_BYTES
        self.old_max_pixels = config.MAX_IMAGE_PIXELS
        self.old_formats = config.ALLOWED_IMAGE_FORMATS

    def tearDown(self):
        self.config.MAX_IMAGE_ATTACHMENT_BYTES = self.old_max_bytes
        self.config.MAX_IMAGE_PIXELS = self.old_max_pixels
        self.config.ALLOWED_IMAGE_FORMATS = self.old_formats

    def _png_bytes(self, size=(2, 2)):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", size, (255, 0, 0)).save(buffer, format="PNG")
        return buffer.getvalue()

    def test_valid_image_bytes_are_loaded_as_rgb(self):
        from attachments import validate_image_bytes

        image = validate_image_bytes(
            self._png_bytes(),
            source_name="unit-test",
            content_type="image/png",
        )

        self.assertEqual(image.mode, "RGB")
        self.assertEqual(image.size, (2, 2))

    def test_rejects_oversized_bytes(self):
        from attachments import ImageValidationError, validate_image_bytes

        self.config.MAX_IMAGE_ATTACHMENT_BYTES = 4

        with self.assertRaises(ImageValidationError):
            validate_image_bytes(
                self._png_bytes(),
                source_name="unit-test",
                content_type="image/png",
            )

    def test_rejects_excessive_pixels(self):
        from attachments import ImageValidationError, validate_image_bytes

        self.config.MAX_IMAGE_PIXELS = 3

        with self.assertRaises(ImageValidationError):
            validate_image_bytes(
                self._png_bytes(size=(2, 2)),
                source_name="unit-test",
                content_type="image/png",
            )

    def test_rejects_corrupt_image(self):
        from attachments import ImageValidationError, validate_image_bytes

        with self.assertRaises(ImageValidationError):
            validate_image_bytes(
                b"not an image",
                source_name="unit-test",
                content_type="image/png",
            )


if __name__ == "__main__":
    unittest.main()
