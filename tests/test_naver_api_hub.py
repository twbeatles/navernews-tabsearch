# pyright: reportMissingModuleSource=false
import unittest

from core.naver_api import (
    NAVER_API_KEY_HEADER,
    NAVER_API_KEY_ID_HEADER,
    NAVER_NEWS_SEARCH_FORMAT,
    NAVER_NEWS_SEARCH_URL,
    format_naver_http_error,
    naver_auth_headers,
    naver_error_hint,
    parse_naver_api_error,
)


class TestNaverApiHubHelpers(unittest.TestCase):
    def test_news_search_url_is_api_hub(self):
        self.assertEqual(
            NAVER_NEWS_SEARCH_URL,
            "https://naverapihub.apigw.ntruss.com/search/v1/news",
        )
        self.assertNotIn("openapi.naver.com", NAVER_NEWS_SEARCH_URL)
        self.assertNotIn("news.json", NAVER_NEWS_SEARCH_URL)

    def test_auth_headers_use_ncp_gateway_names(self):
        headers = naver_auth_headers("  my-id  ", "  my-secret  ")
        self.assertEqual(
            headers,
            {
                "X-NCP-APIGW-API-KEY-ID": "my-id",
                "X-NCP-APIGW-API-KEY": "my-secret",
            },
        )
        self.assertEqual(headers[NAVER_API_KEY_ID_HEADER], "my-id")
        self.assertEqual(headers[NAVER_API_KEY_HEADER], "my-secret")
        self.assertNotIn("X-Naver-Client-Id", headers)
        self.assertNotIn("X-Naver-Client-Secret", headers)

    def test_parse_search_api_flat_error(self):
        code, message = parse_naver_api_error(
            {
                "errorCode": "SE02",
                "errorMessage": "Invalid display value (부적절한 display 값입니다.)",
            }
        )
        self.assertEqual(code, "SE02")
        self.assertIn("display", message)

    def test_parse_gateway_nested_error(self):
        code, message = parse_naver_api_error(
            {
                "error": {
                    "errorCode": "200",
                    "message": "Authentication Failed",
                    "details": "Authentication information are missing.",
                }
            }
        )
        self.assertEqual(code, "200")
        self.assertIn("Authentication Failed", message)
        self.assertIn("missing", message)

    def test_parse_empty_payload(self):
        code, message = parse_naver_api_error({})
        self.assertEqual(code, "")
        self.assertEqual(message, "알 수 없는 오류")

        code2, message2 = parse_naver_api_error(None)
        self.assertEqual(code2, "")
        self.assertEqual(message2, "알 수 없는 오류")

    def test_format_auth_error_is_user_friendly(self):
        text = format_naver_http_error(401, "200", "Authentication Failed")
        self.assertIn("401", text)
        self.assertIn("API HUB", text)
        self.assertIn("Authentication Failed", text)

    def test_search_format_is_json(self):
        self.assertEqual(NAVER_NEWS_SEARCH_FORMAT, "json")

    def test_error_hint_covers_documented_codes(self):
        self.assertIn("display", naver_error_hint("SE02"))
        self.assertIn("1,000", naver_error_hint("SE03"))
        self.assertIn("sort", naver_error_hint("SE04").lower())
        self.assertEqual(naver_error_hint("UNKNOWN_CODE"), "")

    def test_format_bad_request_includes_hint(self):
        text = format_naver_http_error(400, "SE02", "Invalid display value.")
        self.assertIn("400", text)
        self.assertIn("SE02", text)
        self.assertIn("1~100", text)
        self.assertIn("Invalid display value.", text)

    def test_format_rate_limit_mentions_daily_quota(self):
        text = format_naver_http_error(429, "", "Too Many Requests")
        self.assertIn("429", text)
        self.assertIn("25,000", text)
        self.assertIn("Too Many Requests", text)


if __name__ == "__main__":
    unittest.main()
