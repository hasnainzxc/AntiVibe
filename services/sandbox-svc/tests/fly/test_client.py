"""Tests for Fly Machines client using respx for HTTP mocking."""

import json
import os
import pytest
import respx
import httpx
from fly.client import FlyClient, FlyError

MOCK_TOKEN = "fly-test-token-12345"
MOCK_APP = "antivibe-sandbox"
MACHINE_ID = "d8c0a1b2e3f4"


@pytest.fixture
def client():
    return FlyClient(api_token=MOCK_TOKEN, base_url="https://api.machines.dev")


@pytest.fixture
def mock_create(respx_mock):
    return respx_mock.post(
        f"https://api.machines.dev/v1/apps/{MOCK_APP}/machines"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "id": MACHINE_ID,
                "name": "antivibe-sandbox-test",
                "state": "created",
                "region": "iad",
                "config": {"image": "nginx:alpine", "size": "shared-cpu-1x"},
            },
        )
    )


class TestCreateMachine:
    @pytest.mark.asyncio
    async def test_create_success(self, client, mock_create):
        machine = await client.create_machine(
            MOCK_APP, "nginx:alpine", region="iad"
        )
        assert machine["id"] == MACHINE_ID
        assert machine["state"] == "created"
        assert MACHINE_ID in client._destroy_queue  # auto_destroy queued

    @pytest.mark.asyncio
    async def test_create_adds_to_destroy_queue(self, client, mock_create):
        await client.create_machine(MOCK_APP, "nginx:alpine")
        assert MACHINE_ID in client._destroy_queue

    @pytest.mark.asyncio
    async def test_create_no_auto_destroy(self, client, mock_create):
        await client.create_machine(
            MOCK_APP, "nginx:alpine", auto_destroy=False
        )
        assert MACHINE_ID not in client._destroy_queue


class TestNoToken:
    def test_missing_token_raises(self):
        with pytest.raises(FlyError, match="FLY_API_TOKEN is required"):
            FlyClient(api_token="")


class TestWaitForRunning:
    @pytest.mark.asyncio
    async def test_wait_for_running_success(self, client, respx_mock):
        respx_mock.get(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(
            return_value=httpx.Response(
                200, json={"id": MACHINE_ID, "state": "started"}
            )
        )
        machine = await client.wait_for_running(MACHINE_ID, timeout=5)
        assert machine["state"] == "started"

    @pytest.mark.asyncio
    async def test_wait_for_running_timeout(self, client, respx_mock):
        respx_mock.get(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(
            return_value=httpx.Response(
                200, json={"id": MACHINE_ID, "state": "created"}
            )
        )
        with pytest.raises(FlyError, match="timed out"):
            await client.wait_for_running(MACHINE_ID, timeout=0.1)


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_create_wait_destroy_cycle(self, client, respx_mock):
        respx_mock.post(
            f"https://api.machines.dev/v1/apps/{MOCK_APP}/machines"
        ).mock(
            return_value=httpx.Response(
                201, json={"id": MACHINE_ID, "state": "created"}
            )
        )
        respx_mock.get(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(
            return_value=httpx.Response(
                200, json={"id": MACHINE_ID, "state": "started"}
            )
        )
        destroy_route = respx_mock.delete(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(return_value=httpx.Response(200))

        machine = await client.create_machine(MOCK_APP, "nginx:alpine")
        await client.wait_for_running(machine["id"], timeout=5)
        result = await client.destroy_machine(machine["id"])

        assert result is True
        assert destroy_route.called
        assert MACHINE_ID not in client._destroy_queue


class TestCreateMachineErrors:
    @pytest.mark.asyncio
    async def test_create_with_cmd(self, client, respx_mock):
        route = respx_mock.post(
            f"https://api.machines.dev/v1/apps/{MOCK_APP}/machines"
        ).mock(
            return_value=httpx.Response(
                201, json={"id": MACHINE_ID, "state": "created"}
            )
        )
        await client.create_machine(
            MOCK_APP, "nginx:alpine", cmd=["/bin/sh", "-c", "echo hi"]
        )
        sent = json.loads(route.calls.last.request.content)
        assert sent["config"]["init"]["cmd"] == ["/bin/sh", "-c", "echo hi"]

    @pytest.mark.asyncio
    async def test_create_api_error(self, client, respx_mock):
        respx_mock.post(
            f"https://api.machines.dev/v1/apps/{MOCK_APP}/machines"
        ).mock(return_value=httpx.Response(400, text="bad request"))
        with pytest.raises(FlyError, match="Fly API error: 400"):
            await client.create_machine(MOCK_APP, "nginx:alpine")


class TestStreamLogs:
    @pytest.mark.asyncio
    async def test_stream_logs_returns_lines(self, client, respx_mock):
        respx_mock.get(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}/logs"
        ).mock(return_value=httpx.Response(200, text="line1\nline2\nline3"))
        lines = await client.stream_logs(MACHINE_ID)
        assert lines == ["line1", "line2", "line3"]

    @pytest.mark.asyncio
    async def test_stream_logs_empty(self, client, respx_mock):
        respx_mock.get(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}/logs"
        ).mock(return_value=httpx.Response(200, text=""))
        lines = await client.stream_logs(MACHINE_ID)
        assert lines == []


class TestListMachines:
    @pytest.mark.asyncio
    async def test_list_active_machines(self, client, respx_mock):
        respx_mock.get("https://api.machines.dev/v1/apps/machines").mock(
            return_value=httpx.Response(
                200, json=[{"id": MACHINE_ID, "state": "started"}]
            )
        )
        machines = await client.list_active_machines()
        assert len(machines) == 1
        assert machines[0]["id"] == MACHINE_ID


class TestTerminalState:
    @pytest.mark.asyncio
    async def test_wait_for_running_terminal_state(self, client, respx_mock):
        respx_mock.get(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(
            return_value=httpx.Response(
                200, json={"id": MACHINE_ID, "state": "failed"}
            )
        )
        with pytest.raises(FlyError, match="terminal state"):
            await client.wait_for_running(MACHINE_ID, timeout=5)


class TestDestroy:
    @pytest.mark.asyncio
    async def test_destroy_removes_from_queue(self, client, mock_create, respx_mock):
        respx_mock.delete(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(return_value=httpx.Response(200))
        await client.create_machine(MOCK_APP, "nginx:alpine")
        assert MACHINE_ID in client._destroy_queue
        await client.destroy_machine(MACHINE_ID)
        assert MACHINE_ID not in client._destroy_queue

    @pytest.mark.asyncio
    async def test_destroy_failure_returns_false(self, client, mock_create, respx_mock):
        respx_mock.delete(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(return_value=httpx.Response(500))
        result = await client.destroy_machine(MACHINE_ID)
        assert result is False

    @pytest.mark.asyncio
    async def test_destroy_not_in_queue(self, client, respx_mock):
        respx_mock.delete(
            f"https://api.machines.dev/v1/apps/machines/unknown"
        ).mock(return_value=httpx.Response(200))
        result = await client.destroy_machine("unknown")
        assert result is True


class TestClose:
    @pytest.mark.asyncio
    async def test_close_destroys_queued_and_closes_client(self, client, mock_create, respx_mock):
        respx_mock.delete(
            f"https://api.machines.dev/v1/apps/machines/{MACHINE_ID}"
        ).mock(return_value=httpx.Response(200))
        await client.create_machine(MOCK_APP, "nginx:alpine")
        assert MACHINE_ID in client._destroy_queue
        await client.close()
        assert MACHINE_ID not in client._destroy_queue
        assert client._httpx_client is None
