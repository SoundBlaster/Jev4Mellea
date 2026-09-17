"""Real Mellea Requirement.validate hook, fake context, mocked Jev HTTP.

No generator and no paid calls. This is a bridge integration test, NOT an
end-to-end Mellea generation/repair test. Missing Mellea skips this module.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

pytest.importorskip("mellea", reason="Install .[mellea,dev] to test the real bridge.")
from mellea.core import Context, Requirement, ValidationResult

from mellea_jev import JevClient, JevVerifier, ReviewRequired

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("p,expected", [(0.98, True), (0.02, False), (0.5, None)])
def test_real_requirement_validate_hook(p, expected):
    context = Mock(spec=Context)
    context.last_output.return_value = SimpleNamespace(value="Hello")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "model": "jev-integration-fixture",
        "answers": {"requirement": {"type": "noul", "noul": p}},
        "usage": {"input_tokens": 20, "output_tokens": 2},
    }))
    with JevClient("test", transport=transport) as client:
        req = JevVerifier(client, "The answer is polite.").as_requirement()
        assert isinstance(req, Requirement)
        if expected is None:
            with pytest.raises(ReviewRequired):
                asyncio.run(req.validate(backend=None, ctx=context))
        else:
            result = asyncio.run(req.validate(backend=None, ctx=context))
            assert isinstance(result, ValidationResult)
            assert bool(result) is expected
            assert result.score == p
