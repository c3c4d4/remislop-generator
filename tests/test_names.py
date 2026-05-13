import unittest

from names import generate_job_name


class NameTests(unittest.TestCase):
    def test_generate_job_name_is_seeded_phrase(self):
        first = generate_job_name("abc")
        second = generate_job_name("abc")

        self.assertEqual(first, second)
        self.assertEqual(len(first.split("-")), 3)


if __name__ == "__main__":
    unittest.main()
