import unittest

from validation import parse_time, validate_request


class ValidationTests(unittest.TestCase):
    def test_parse_time_accepts_seconds_and_clock_formats(self):
        self.assertEqual(parse_time("75"), 75)
        self.assertEqual(parse_time("01:15"), 75)
        self.assertEqual(parse_time("1:02:03"), 3723)

    def test_parse_time_rejects_invalid_values(self):
        self.assertIsNone(parse_time(""))
        self.assertIsNone(parse_time("abc"))
        self.assertIsNone(parse_time("1:99"))

    def test_validate_request_returns_actionable_errors(self):
        result = validate_request(
            {
                "board_url": "not-a-url",
                "youtube_url": "https://youtube.com/watch?v=x",
                "start_time": "20",
                "end_time": "10",
                "frame_rate": "40",
            },
            max_duration_seconds=300,
        )

        self.assertIn("Invalid image source URL: not-a-url", result["errors"])
        self.assertIn("End time must be greater than start time.", result["errors"])
        self.assertIn("Frame rate must be between 1 and 30.", result["errors"])

    def test_validate_request_allows_upload_without_image_url(self):
        result = validate_request(
            {
                "board_url": "",
                "youtube_url": "https://youtube.com/watch?v=x",
                "start_time": "0",
                "end_time": "10",
                "frame_rate": "10",
            },
            max_duration_seconds=300,
            has_upload=True,
        )

        self.assertEqual(result["errors"], [])

    def test_validate_request_accepts_multiple_image_urls(self):
        result = validate_request(
            {
                "board_urls": "https://example.com/a\nhttps://example.com/b",
                "youtube_url": "https://youtube.com/watch?v=x",
                "start_time": "0",
                "video_length": "10",
                "end_time": "",
                "frame_rate": "10",
            },
            max_duration_seconds=300,
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["data"]["board_urls"], ["https://example.com/a", "https://example.com/b"])

    def test_validate_request_accepts_video_length(self):
        result = validate_request(
            {
                "board_url": "https://example.com/images",
                "youtube_url": "https://youtube.com/watch?v=x",
                "start_time": "1:00",
                "video_length": "0:30",
                "end_time": "",
                "frame_rate": "10",
            },
            max_duration_seconds=300,
        )

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["data"]["start_seconds"], 60)
        self.assertEqual(result["data"]["end_seconds"], 90)
        self.assertEqual(result["data"]["duration_seconds"], 30)

    def test_validate_request_requires_length_or_end(self):
        result = validate_request(
            {
                "board_url": "https://example.com/images",
                "youtube_url": "https://youtube.com/watch?v=x",
                "start_time": "1:00",
                "video_length": "",
                "end_time": "",
                "frame_rate": "10",
            },
            max_duration_seconds=300,
        )

        self.assertIn("Enter a video length or end time.", result["errors"])


if __name__ == "__main__":
    unittest.main()
