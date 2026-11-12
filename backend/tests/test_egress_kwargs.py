from unittest.mock import AsyncMock, MagicMock

from app.models import Instance
from app.routers.instances import _egress_kwargs
from app.services.k8s_instances import K8sInstanceRuntime


async def test_egress_kwargs_empty_when_owner_row_missing():
    runtime = MagicMock(spec=K8sInstanceRuntime)
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    inst = Instance(template_id="t", owner_id="ghost", name="n", subdomain="n")
    assert await _egress_kwargs(runtime, session, inst) == {}
    session.get.assert_awaited_once()
