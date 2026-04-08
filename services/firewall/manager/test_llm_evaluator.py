import unittest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from llm_evaluator import _build_user_message, _parse_llm_response, evaluate_request


class TestBuildUserMessage(unittest.TestCase):
    def test_basic_message(self):
        msg = _build_user_message("example.com", "https://example.com/path", "GET",
                                   {"Accept": "text/html"}, None, "Python app")
        self.assertIn("Domain: example.com", msg)
        self.assertIn("Method: GET", msg)
        self.assertIn("Project: Python app", msg)

    def test_body_truncation(self):
        body = b"x" * 8000
        msg = _build_user_message("x.com", "https://x.com/", "POST", {}, body, "")
        self.assertIn("8000 bytes", msg)
        self.assertIn("showing first 4096", msg)

    def test_sensitive_headers_filtered(self):
        headers = {"Authorization": "Bearer secret", "Accept": "text/html", "Cookie": "session=abc"}
        msg = _build_user_message("x.com", "https://x.com/", "GET", headers, None, "")
        self.assertNotIn("secret", msg)
        self.assertNotIn("session=abc", msg)
        self.assertIn("Accept", msg)


class TestParseLLMResponse(unittest.TestCase):
    def test_valid_approve(self):
        result = _parse_llm_response('{"decision": "approve", "reasoning": "Safe domain"}')
        self.assertEqual(result["decision"], "approve")
        self.assertEqual(result["reasoning"], "Safe domain")

    def test_valid_deny(self):
        result = _parse_llm_response('{"decision": "deny", "reasoning": "Suspicious"}')
        self.assertEqual(result["decision"], "deny")

    def test_valid_escalate(self):
        result = _parse_llm_response('{"decision": "escalate", "reasoning": "Uncertain"}')
        self.assertEqual(result["decision"], "escalate")

    def test_invalid_json_returns_escalate(self):
        result = _parse_llm_response("not json at all")
        self.assertEqual(result["decision"], "escalate")

    def test_invalid_decision_returns_escalate(self):
        result = _parse_llm_response('{"decision": "maybe", "reasoning": "dunno"}')
        self.assertEqual(result["decision"], "escalate")

    def test_markdown_code_block_stripped(self):
        result = _parse_llm_response('```json\n{"decision": "approve", "reasoning": "OK"}\n```')
        self.assertEqual(result["decision"], "approve")


class TestEvaluateRequest(unittest.TestCase):
    def test_no_credentials_returns_escalate(self):
        """When Azure credentials are not configured, returns escalate."""
        with patch("llm_evaluator.AZURE_ENDPOINT", ""), patch("llm_evaluator.AZURE_API_KEY", ""):
            result = asyncio.run(evaluate_request("x.com", "https://x.com/", "GET", {}, None))
            self.assertEqual(result["decision"], "escalate")

    def test_timeout_returns_escalate(self):
        """When LLM call times out, returns escalate."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_client.close = AsyncMock()

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncAzureOpenAI.return_value = mock_client

        with patch("llm_evaluator.AZURE_ENDPOINT", "https://test.openai.azure.com"), \
             patch("llm_evaluator.AZURE_API_KEY", "test-key"), \
             patch.dict("sys.modules", {"openai": mock_openai_module}):
            result = asyncio.run(evaluate_request("x.com", "https://x.com/", "GET", {}, None))

        self.assertEqual(result["decision"], "escalate")
        self.assertIn("timeout", result["reasoning"].lower())

    def test_api_error_returns_escalate(self):
        """When Azure API returns an error, returns escalate."""
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API rate limit exceeded"))
        mock_client.close = AsyncMock()

        mock_openai_module = MagicMock()
        mock_openai_module.AsyncAzureOpenAI.return_value = mock_client

        with patch("llm_evaluator.AZURE_ENDPOINT", "https://test.openai.azure.com"), \
             patch("llm_evaluator.AZURE_API_KEY", "test-key"), \
             patch.dict("sys.modules", {"openai": mock_openai_module}):
            result = asyncio.run(evaluate_request("x.com", "https://x.com/", "GET", {}, None))

        self.assertEqual(result["decision"], "escalate")
        self.assertIn("error", result["reasoning"].lower())


if __name__ == "__main__":
    unittest.main()
