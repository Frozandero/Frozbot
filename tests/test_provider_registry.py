import importlib.util
import os
import unittest
from unittest.mock import patch


class ProviderRegistryTests(unittest.TestCase):
    def test_available_provider_names_include_all_providers(self):
        from llm_providers import available_provider_names

        self.assertEqual(
            available_provider_names(),
            ("gemini", "mistral", "xai", "openrouter"),
        )

    def test_get_provider_returns_none_for_missing_key(self):
        from llm_providers import get_provider

        with patch.dict(os.environ, {"LLM_PROVIDER": "mistral"}, clear=True):
            self.assertIsNone(get_provider())

    @unittest.skipUnless(
        importlib.util.find_spec("PIL") is not None,
        "Pillow is required to instantiate MistralProvider",
    )
    def test_get_provider_can_select_mistral_without_importing_other_sdks(self):
        from llm_providers import get_provider

        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "mistral",
                "MISTRAL_API_KEY": "test-key",
            },
            clear=True,
        ):
            provider = get_provider()

        self.assertEqual(provider.provider_name, "mistral")

    @unittest.skipUnless(
        importlib.util.find_spec("PIL") is not None,
        "Pillow is required to instantiate OpenRouterProvider",
    )
    def test_get_provider_can_select_openrouter_without_importing_other_sdks(self):
        from llm_providers import get_provider

        with patch.dict(
            os.environ,
            {
                "LLM_PROVIDER": "openrouter",
                "OPENROUTER_API_KEY": "test-key",
            },
            clear=True,
        ):
            provider = get_provider()

        self.assertEqual(provider.provider_name, "openrouter")


if __name__ == "__main__":
    unittest.main()
