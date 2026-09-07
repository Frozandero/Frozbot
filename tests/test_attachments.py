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
        self.old_max_audio_bytes = config.MAX_AUDIO_ATTACHMENT_BYTES
        self.old_max_video_bytes = config.MAX_VIDEO_ATTACHMENT_BYTES
        self.old_audio_formats = config.ALLOWED_AUDIO_FORMATS
        self.old_video_formats = config.ALLOWED_VIDEO_FORMATS

    def tearDown(self):
        self.config.MAX_IMAGE_ATTACHMENT_BYTES = self.old_max_bytes
        self.config.MAX_IMAGE_PIXELS = self.old_max_pixels
        self.config.ALLOWED_IMAGE_FORMATS = self.old_formats
        self.config.MAX_AUDIO_ATTACHMENT_BYTES = self.old_max_audio_bytes
        self.config.MAX_VIDEO_ATTACHMENT_BYTES = self.old_max_video_bytes
        self.config.ALLOWED_AUDIO_FORMATS = self.old_audio_formats
        self.config.ALLOWED_VIDEO_FORMATS = self.old_video_formats

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

    def test_validates_audio_as_binary_media(self):
        from attachments import validate_binary_media_bytes

        media = validate_binary_media_bytes(
            b"test-audio",
            source_name="unit-test",
            content_type="audio/mpeg",
            filename="clip.mp3",
        )

        self.assertEqual(media.data, b"test-audio")
        self.assertEqual(media.mime_type, "audio/mpeg")
        self.assertEqual(media.filename, "clip.mp3")

    def test_rejects_oversized_video(self):
        from attachments import MediaValidationError, validate_binary_media_bytes

        self.config.MAX_VIDEO_ATTACHMENT_BYTES = 4

        with self.assertRaises(MediaValidationError):
            validate_binary_media_bytes(
                b"video",
                source_name="unit-test",
                content_type="video/mp4",
                filename="clip.mp4",
            )

    def test_rejects_unsupported_audio_format(self):
        from attachments import MediaValidationError, validate_binary_media_bytes

        with self.assertRaises(MediaValidationError):
            validate_binary_media_bytes(
                b"audio",
                source_name="unit-test",
                content_type="audio/x-custom",
                filename="clip.custom",
            )


if __name__ == "__main__":
    unittest.main()
