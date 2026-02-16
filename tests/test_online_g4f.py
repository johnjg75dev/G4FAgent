from __future__ import annotations

import os
import unittest

from g4fagent.core import G4FManager, LLMConfig, resolve_model_name
from g4fagent.utils import msg

from tests.helpers import make_runtime_cfg


class TestOnlineG4F(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.getenv("G4F_ONLINE_TESTS", "0") != "1":
            raise unittest.SkipTest("Online tests are disabled. Set G4F_ONLINE_TESTS=1 to run them.")

    def test_live_chat_completion_returns_text(self) -> None:
        manager = G4FManager.from_runtime_config(
            make_runtime_cfg(),
            cfg=LLMConfig(max_retries=0, log_requests=False),
        )
        model = resolve_model_name(None)

        try:
            response = manager.chat(
                messages=[msg("user", "Reply with a short confirmation.")],
                model=model,
                create_kwargs={"timeout": 30},
                max_retries=0,
            )
        except Exception as e:
            self.skipTest(f"Online provider unavailable: {e}")

        self.assertIsInstance(response, str)
        self.assertTrue(response.strip())


if __name__ == "__main__":
    unittest.main()

