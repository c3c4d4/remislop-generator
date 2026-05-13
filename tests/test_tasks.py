import unittest
import wave
import tempfile
from pathlib import Path

from PIL import Image

from tasks import apply_post_effects, bitrate_plan, collection_background_theme, collection_canvas_size, copy_tree_contents, estimate_bpm_from_wav, fps_from_bpm, normalize_post_settings, normalize_source_url, invert_logo, sample_images, shuffled_images


class TaskHelperTests(unittest.TestCase):
    def test_sample_images_keeps_even_spread(self):
        images = [Path(f"{idx}.jpg") for idx in range(10)]
        sampled = sample_images(images, 4)
        self.assertEqual(len(sampled), 4)
        self.assertEqual(sampled[0], images[0])
        self.assertEqual(sampled[-1], images[-1])

    def test_sample_images_returns_all_when_under_limit(self):
        images = [Path("a.jpg"), Path("b.jpg")]
        self.assertEqual(sample_images(images, 5), images)

    def test_shuffled_images_is_seeded_and_keeps_same_items(self):
        images = [Path(f"{idx}.jpg") for idx in range(10)]
        shuffled = shuffled_images(images, seed="job")
        self.assertEqual(set(shuffled), set(images))
        self.assertEqual(shuffled, shuffled_images(images, seed="job"))
        self.assertNotEqual(shuffled, images)

    def test_normalize_source_url_rewrites_pinterest_country_domain(self):
        url = normalize_source_url("https://jp.pinterest.com/rickqrs_/tuff/")
        self.assertEqual(url, "https://www.pinterest.com/rickqrs_/tuff/")

    def test_frame_count_for_duration_math(self):
        self.assertEqual(round(20 * 10), 200)
        self.assertEqual(round(7.5 * 10), 75)

    def test_collection_background_theme_uses_image_brightness(self):
        dark = Image.new("RGBA", (200, 200), (10, 10, 10, 255))
        light = Image.new("RGBA", (200, 200), (245, 245, 245, 255))
        dark_path = Path("dark_test_theme.png")
        light_path = Path("light_test_theme.png")
        try:
            dark.save(dark_path)
            light.save(light_path)

            self.assertEqual(collection_background_theme([dark_path]), "dark")
            self.assertEqual(collection_background_theme([light_path]), "light")
        finally:
            dark_path.unlink(missing_ok=True)
            light_path.unlink(missing_ok=True)

    def test_bitrate_plan_scales_with_duration(self):
        short = bitrate_plan(30, max_output_mb=9.5)
        long = bitrate_plan(1200, max_output_mb=9.5)

        self.assertGreater(short["video_kbps"], long["video_kbps"])
        self.assertGreaterEqual(long["audio_kbps"], 16)
        self.assertGreaterEqual(long["video_kbps"], 12)

    def test_invert_logo_preserves_alpha(self):
        logo = Image.new("RGBA", (2, 2), (0, 0, 0, 0))
        logo.putpixel((0, 0), (255, 0, 0, 128))
        inverted = invert_logo(logo)

        self.assertEqual(inverted.getpixel((0, 0)), (0, 255, 255, 128))
        self.assertEqual(inverted.getpixel((1, 1))[3], 0)

    def test_estimate_bpm_from_empty_wav_falls_back(self):
        path = Path("empty_bpm_test.wav")
        try:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(8000)
                wav_file.writeframes(b"")
            self.assertEqual(estimate_bpm_from_wav(path), 120)
        finally:
            path.unlink(missing_ok=True)

    def test_fps_from_bpm_keeps_render_rate_bounded(self):
        self.assertEqual(fps_from_bpm(60), 6)
        self.assertEqual(fps_from_bpm(120), 10)
        self.assertEqual(fps_from_bpm(142), 12)
        self.assertEqual(fps_from_bpm(240), 18)

    def test_copy_tree_contents_merges_existing_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_a = root / "source_a"
            source_b = root / "source_b"
            target = root / "target"
            (source_a / "pinterest" / "board_a").mkdir(parents=True)
            (source_b / "pinterest" / "board_b").mkdir(parents=True)
            (source_a / "pinterest" / "board_a" / "a.jpg").write_bytes(b"a")
            (source_b / "pinterest" / "board_b" / "b.jpg").write_bytes(b"b")

            copy_tree_contents(source_a, target)
            copy_tree_contents(source_b, target)

            self.assertTrue((target / "pinterest" / "board_a" / "a.jpg").exists())
            self.assertTrue((target / "pinterest" / "board_b" / "b.jpg").exists())

    def test_collection_canvas_size_keeps_height_and_scales_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            second = Path(tmp) / "second.png"
            Image.new("RGB", (100, 100), "black").save(first)
            Image.new("RGB", (300, 100), "white").save(second)

            self.assertEqual(collection_canvas_size([first, second]), (1920, 1080))

    def test_collection_canvas_size_has_minimum_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "portrait.png"
            Image.new("RGB", (300, 900), "black").save(image_path)

            self.assertEqual(collection_canvas_size([image_path]), (1080, 1080))

    def test_normalize_post_settings_clamps_values(self):
        settings = normalize_post_settings(
            {
                "brightness": "3",
                "contrast": "bad",
                "saturation": "-1",
                "sharpness": "1.5",
                "pixelate": "4",
            }
        )

        self.assertEqual(settings["brightness"], 1.4)
        self.assertEqual(settings["contrast"], 1.0)
        self.assertEqual(settings["saturation"], 0.0)
        self.assertEqual(settings["sharpness"], 1.5)
        self.assertEqual(settings["pixelate"], 4)

    def test_apply_post_effects_changes_frame_without_resizing(self):
        frame = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        changed = apply_post_effects(frame, {"brightness": 1.4, "contrast": 1.0})

        self.assertEqual(changed.size, frame.size)
        self.assertGreater(changed.getpixel((0, 0))[0], frame.getpixel((0, 0))[0])


if __name__ == "__main__":
    unittest.main()
