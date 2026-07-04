"""Tests for sandbox health monitor.

All Fly API calls mocked via FlyClient. No real network, no real HTTP,
no real logs. Tests verify boot detection, crash recovery, log streaming,
and slow-boot warnings.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from fly.client import FlyError
from sandbox.health_monitor import (
    SandboxCrashError,
    SandboxHealth,
    SandboxHealthMonitor,
)

# ─── Fixtures ─────────────────────────────────────────────────────────


def _make_fly_client() -> MagicMock:
    """Mock FlyClient with async methods."""
    client = MagicMock()
    client.wait_for_running = AsyncMock(
        return_value={"id": "machine-abc-123", "state": "started"}
    )
    client.stream_logs = AsyncMock(return_value=["line1", "line2", "line3"])
    client.destroy_machine = AsyncMock(return_value=True)
    client.create_machine = AsyncMock(
        return_value={"id": "machine-new-456", "state": "starting"}
    )
    return client


@pytest.fixture
def fly_client():
    return _make_fly_client()


@pytest.fixture
def monitor(fly_client):
    return SandboxHealthMonitor(fly_client=fly_client)


# ─── SandboxHealth dataclass ──────────────────────────────────────────


class TestSandboxHealth:
    def test_health_stores_all_fields(self):
        h = SandboxHealth(
            boot_duration_ms=1500,
            ready=True,
            logs=["log1", "log2"],
            crash_signal=False,
        )
        assert h.boot_duration_ms == 1500
        assert h.ready is True
        assert h.logs == ["log1", "log2"]
        assert h.crash_signal is False

    def test_health_defaults(self):
        h = SandboxHealth(boot_duration_ms=0, ready=False)
        assert h.logs == []
        assert h.crash_signal is False


# ─── SandboxCrashError ────────────────────────────────────────────────


class TestSandboxCrashError:
    def test_error_stores_machine_id(self):
        err = SandboxCrashError("recovery failed", machine_id="m1")
        assert str(err) == "recovery failed"
        assert err.machine_id == "m1"

    def test_error_without_machine_id(self):
        err = SandboxCrashError("recovery failed")
        assert err.machine_id is None


# ─── health() ─────────────────────────────────────────────────────────


class TestHealth:
    async def test_health_returns_ready_true_when_machine_starts(
        self, monitor, fly_client
    ):
        """Machine reaches 'started' state within timeout → ready=True."""
        result = await monitor.health("machine-abc-123", boot_timeout_s=120)

        assert result.ready is True
        assert result.boot_duration_ms >= 0
        assert result.crash_signal is False
        fly_client.wait_for_running.assert_awaited_once_with(
            "machine-abc-123", timeout=120
        )

    async def test_health_returns_ready_false_on_timeout(
        self, monitor, fly_client
    ):
        """wait_for_running raises FlyError (timeout) → ready=False."""
        fly_client.wait_for_running = AsyncMock(
            side_effect=FlyError("Machine timed out", machine_id="machine-abc-123")
        )

        result = await monitor.health("machine-abc-123", boot_timeout_s=5)

        assert result.ready is False
        assert result.boot_duration_ms >= 0
        assert result.crash_signal is False

    async def test_boot_duration_ms_captured(self, monitor, fly_client):
        """boot_duration_ms reflects actual time spent waiting."""
        # Simulate a 100ms delay in wait_for_running
        async def slow_wait(*args, **kwargs):
            await asyncio.sleep(0.1)
            return {"id": "machine-abc-123", "state": "started"}

        fly_client.wait_for_running = AsyncMock(side_effect=slow_wait)

        result = await monitor.health("machine-abc-123", boot_timeout_s=120)

        assert result.ready is True
        # Should be at least 100ms (allowing for timing variance)
        assert result.boot_duration_ms >= 90
        assert result.boot_duration_ms < 500  # sanity upper bound

    async def test_health_uses_default_timeout(self, monitor, fly_client):
        """Default boot_timeout_s is 120."""
        await monitor.health("machine-abc-123")

        fly_client.wait_for_running.assert_awaited_once_with(
            "machine-abc-123", timeout=120
        )

    async def test_slow_boot_warns(self, monitor, fly_client, monkeypatch, caplog):
        """Boot time > 5s logs boot.slow warning."""
        import sandbox.health_monitor as hm

        # Mock time.monotonic to simulate 6s boot
        real_monotonic = time.monotonic
        call_count = [0]

        def fake_monotonic():
            call_count[0] += 1
            if call_count[0] == 1:
                return real_monotonic()  # start time
            return real_monotonic() + 6.0  # end time = start + 6s

        monkeypatch.setattr(hm.time, "monotonic", fake_monotonic)

        # Capture structlog warnings
        import structlog
        from structlog.testing import LogCapture

        log_capture = LogCapture()
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                log_capture,
            ],
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=False,
        )

        result = await monitor.health("machine-abc-123", boot_timeout_s=120)

        assert result.ready is True
        assert result.boot_duration_ms >= 6000

        # Check that boot.slow was logged
        log_entries = log_capture.entries
        slow_boot_logs = [
            e for e in log_entries
            if e.get("event") == "boot.slow"
        ]
        assert len(slow_boot_logs) > 0, "Expected boot.slow warning"
        assert slow_boot_logs[0]["machine_id"] == "machine-abc-123"


# ─── stream_logs() ────────────────────────────────────────────────────


class TestStreamLogs:
    async def test_stream_logs_wraps_fly_client(self, monitor, fly_client):
        """stream_logs yields lines from fly_client.stream_logs."""
        fly_client.stream_logs = AsyncMock(
            return_value=["line1", "line2", "line3"]
        )

        lines = []
        async for line in monitor.stream_logs("machine-abc-123"):
            lines.append(line)

        assert lines == ["line1", "line2", "line3"]
        fly_client.stream_logs.assert_awaited_once_with("machine-abc-123")

    async def test_stream_logs_empty(self, monitor, fly_client):
        """stream_logs handles empty log list."""
        fly_client.stream_logs = AsyncMock(return_value=[])

        lines = []
        async for line in monitor.stream_logs("machine-abc-123"):
            lines.append(line)

        assert lines == []

    async def test_stream_logs_single_line(self, monitor, fly_client):
        """stream_logs handles single log line."""
        fly_client.stream_logs = AsyncMock(return_value=["single line"])

        lines = []
        async for line in monitor.stream_logs("machine-abc-123"):
            lines.append(line)

        assert lines == ["single line"]


# ─── crash_recovery() ─────────────────────────────────────────────────


class TestCrashRecovery:
    async def test_crash_recovery_destroys_and_creates(
        self, monitor, fly_client
    ):
        """crash_recovery destroys old machine and creates new one."""
        new_id = await monitor.crash_recovery(
            machine_id="machine-old-123",
            app_name="antivibe-sandbox",
            image="registry/antivibe:abc",
            max_attempts=2,
        )

        assert new_id == "machine-new-456"
        fly_client.destroy_machine.assert_awaited_once_with("machine-old-123")
        fly_client.create_machine.assert_awaited_once()
        kwargs = fly_client.create_machine.await_args.kwargs
        assert kwargs["app_name"] == "antivibe-sandbox"
        assert kwargs["image"] == "registry/antivibe:abc"
        assert kwargs["auto_destroy"] is True

    async def test_crash_recovery_returns_new_machine_id(
        self, monitor, fly_client
    ):
        """crash_recovery returns the new machine_id from create_machine."""
        fly_client.create_machine = AsyncMock(
            return_value={"id": "machine-recovered-789", "state": "starting"}
        )

        new_id = await monitor.crash_recovery(
            machine_id="machine-old-123",
            app_name="antivibe-sandbox",
            image="registry/antivibe:abc",
        )

        assert new_id == "machine-recovered-789"

    async def test_crash_recovery_raises_after_max_attempts(
        self, monitor, fly_client
    ):
        """crash_recovery raises SandboxCrashError after max_attempts failures."""
        # Make both destroy and create fail
        fly_client.destroy_machine = AsyncMock(
            side_effect=FlyError("destroy failed", machine_id="machine-old-123")
        )

        with pytest.raises(SandboxCrashError) as exc_info:
            await monitor.crash_recovery(
                machine_id="machine-old-123",
                app_name="antivibe-sandbox",
                image="registry/antivibe:abc",
                max_attempts=2,
            )

        assert exc_info.value.machine_id == "machine-old-123"
        assert "failed after 2 attempts" in str(exc_info.value)
        # Should have tried 2 times
        assert fly_client.destroy_machine.await_count == 2

    async def test_crash_recovery_retries_on_create_failure(
        self, monitor, fly_client
    ):
        """crash_recovery retries if create_machine fails."""
        # First attempt: destroy succeeds, create fails
        # Second attempt: both succeed
        fly_client.destroy_machine = AsyncMock(return_value=True)
        fly_client.create_machine = AsyncMock(
            side_effect=[
                FlyError("create failed"),
                {"id": "machine-retry-999", "state": "starting"},
            ]
        )

        new_id = await monitor.crash_recovery(
            machine_id="machine-old-123",
            app_name="antivibe-sandbox",
            image="registry/antivibe:abc",
            max_attempts=2,
        )

        assert new_id == "machine-retry-999"
        assert fly_client.destroy_machine.await_count == 2
        assert fly_client.create_machine.await_count == 2

    async def test_crash_recovery_default_max_attempts(
        self, monitor, fly_client
    ):
        """Default max_attempts is 2."""
        fly_client.destroy_machine = AsyncMock(
            side_effect=FlyError("destroy failed")
        )

        with pytest.raises(SandboxCrashError):
            await monitor.crash_recovery(
                machine_id="machine-old-123",
                app_name="antivibe-sandbox",
                image="registry/antivibe:abc",
            )

        # Default max_attempts=2 → 2 destroy attempts
        assert fly_client.destroy_machine.await_count == 2


# ─── No real network ─────────────────────────────────────────────────


class TestNoRealNetwork:
    async def test_no_real_fly_api_calls(self, monitor, fly_client):
        """Verify FlyClient mock was used (no real httpx calls)."""
        result = await monitor.health("machine-abc-123")

        # Mock was definitely called → no real network was needed
        fly_client.wait_for_running.assert_awaited_once()
        assert result.ready is True

    async def test_no_real_log_streaming(self, monitor, fly_client):
        """Verify stream_logs uses mock (no real HTTP)."""
        fly_client.stream_logs = AsyncMock(return_value=["mocked log"])

        lines = []
        async for line in monitor.stream_logs("machine-abc-123"):
            lines.append(line)

        fly_client.stream_logs.assert_awaited_once()
        assert lines == ["mocked log"]
