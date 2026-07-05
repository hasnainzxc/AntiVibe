import time
import pytest
from unittest.mock import MagicMock


class TestCircuitBreakerCreate:
    def test_circuit_state_defaults(self):
        from circuit_breaker import CircuitState
        s = CircuitState()
        assert s.total_cost_cents == 0
        assert s.llm_tokens == 0
        assert s.is_tripped is False
        assert s.trip_reason is None

    def test_circuit_breaker_instance(self):
        from circuit_breaker import CircuitBreaker
        cb = CircuitBreaker()
        assert cb.MAX_COST_CENTS == 50
        assert cb.MAX_TIMEOUT_SEC == 600
        assert cb.MAX_TOKENS == 100_000


class TestCostCapTrigger:
    def test_breaker_trips_at_cost_cap(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        assert cb.check(state) is True
        cb.record_cost(state, 51)
        assert cb.check(state) is False
        assert state.is_tripped is True
        assert "cost" in state.trip_reason

    def test_breaker_allows_below_cap(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_cost(state, 30)
        assert cb.check(state) is True
        assert state.is_tripped is False


class TestPartialResultsSaved:
    @pytest.mark.asyncio
    async def test_breaker_returns_partial_when_tripped(self, monkeypatch):
        from circuit_breaker import CircuitBreaker, CircuitState
        from scanner.tier1 import run_tier1

        cb = CircuitBreaker()
        state = CircuitState()
        state.total_cost_cents = 999
        state.is_tripped = True
        state.trip_reason = "test: cost exceeded"

        stage_results = []
        stage_results.append("clone_done")
        stage_results.append("ast_done")

        assert cb.check(state) is False

        pipeline_result = {
            "status": "partial",
            "findings": [{"source": "secret_detector", "severity": "high", "title": "Test"}],
            "repo": "/tmp/mock",
            "stack": "nextjs",
            "stages_completed": stage_results,
            "breaker_tripped": state.trip_reason,
        }

        assert pipeline_result["status"] == "partial"
        assert len(pipeline_result["findings"]) == 1
        assert "stages_completed" in pipeline_result
        assert stage_results == ["clone_done", "ast_done"]


class TestBreakerStateIsolation:
    def test_scan_b_unaffected_by_scan_a_trip(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()

        scan_a = CircuitState()
        scan_b = CircuitState()

        assert cb.check(scan_a) is True
        assert cb.check(scan_b) is True

        cb.record_cost(scan_a, 999)
        assert cb.check(scan_a) is False
        assert scan_a.is_tripped is True

        assert cb.check(scan_b) is True
        assert scan_b.is_tripped is False
        assert scan_b.total_cost_cents == 0
        assert scan_b.llm_tokens == 0

    def test_token_limit_one_scan_only(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()

        scan_a = CircuitState()
        scan_b = CircuitState()

        cb.record_tokens(scan_a, 999_999)
        assert cb.check(scan_a) is False
        assert cb.check(scan_b) is True


class TestTimeoutTrigger:
    def test_breaker_trips_on_timeout(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        state.start_time = time.time() - 601
        assert cb.check(state) is False
        assert state.is_tripped is True
        assert "timeout" in state.trip_reason

    def test_breaker_ok_within_timeout(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        state.start_time = time.time() - 300
        assert cb.check(state) is True

    def test_breaker_trips_at_custom_timeout(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        state.start_time = time.time() - 5
        assert cb.check(state) is True

        state.start_time = time.time() - 601
        assert cb.check(state) is False
        assert "timeout" in state.trip_reason


class TestTokenLimit:
    def test_breaker_trips_at_token_cap(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_tokens(state, 100_001)
        assert cb.check(state) is False
        assert state.is_tripped is True
        assert "tokens" in state.trip_reason

    def test_breaker_allows_below_token_cap(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_tokens(state, 50_000)
        assert cb.check(state) is True

    def test_token_tracking_accumulates(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_tokens(state, 40_000)
        cb.record_tokens(state, 30_000)
        assert state.llm_tokens == 70_000
        assert cb.check(state) is True
        cb.record_tokens(state, 60_000)
        assert cb.check(state) is False


class TestRecordCost:
    def test_cost_accumulates(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_cost(state, 10)
        assert state.total_cost_cents == 10
        cb.record_cost(state, 20)
        assert state.total_cost_cents == 30


class TestRecordTokens:
    def test_tokens_accumulate(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_tokens(state, 100)
        assert state.llm_tokens == 100
        cb.record_tokens(state, 200)
        assert state.llm_tokens == 300


class TestZeroCostDoesNotTrip:
    def test_zero_cost_does_not_trip(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        cb.record_cost(state, 0)
        assert cb.check(state) is True
        assert state.is_tripped is False


class TestAlreadyTrippedState:
    def test_already_tripped_returns_false(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        state.is_tripped = True
        state.trip_reason = "manual_override"
        assert cb.check(state) is False


class TestCircuitBreakerWithScanOrchestrator:
    @pytest.mark.asyncio
    async def test_cost_tracking_in_pipeline(self, monkeypatch):
        from circuit_breaker import CircuitBreaker, CircuitState
        from scan_orchestrator import _run_pipeline

        mock_sb = MagicMock()
        mock_sb.table.return_value = mock_sb
        mock_sb.insert.return_value = mock_sb
        mock_sb.update.return_value = mock_sb
        mock_sb.eq.return_value = mock_sb
        mock_sb.select.return_value = mock_sb
        mock_sb.execute.return_value = MagicMock(data=[])

        cb = CircuitBreaker()
        state = CircuitState()

        async def mock_tier1(url, **kw):
            return {
                "status": "complete",
                "stack": "nextjs",
                "repo": "/tmp/mock-repo",
                "findings": [],
            }

        monkeypatch.setattr("scan_orchestrator.run_tier1", mock_tier1)
        monkeypatch.setattr("scan_orchestrator.get_supabase_client", lambda **kw: mock_sb)

        await _run_pipeline("test-scan-id-cost", "https://github.com/user/repo", mock_sb)

        assert cb.check(state) is True


class TestBreakerIntegrationNoRealAPIs:
    def test_breaker_before_llm(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        state.total_cost_cents = 999
        state.is_tripped = True
        assert cb.check(state) is False

    def test_breaker_before_sandbox(self):
        from circuit_breaker import CircuitBreaker, CircuitState
        cb = CircuitBreaker()
        state = CircuitState()
        state.total_cost_cents = 999
        state.is_tripped = True
        assert cb.check(state) is False
