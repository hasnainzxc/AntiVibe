import time
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CircuitState:
    total_cost_cents: float = 0
    llm_tokens: int = 0
    start_time: float = field(default_factory=time.time)
    is_tripped: bool = False
    trip_reason: str | None = None


class CircuitBreaker:
    MAX_COST_CENTS = 50
    MAX_TIMEOUT_SEC = 600
    MAX_TOKENS = 100_000

    def check(self, state: CircuitState) -> bool:
        if state.is_tripped:
            return False

        elapsed = time.time() - state.start_time
        if elapsed > self.MAX_TIMEOUT_SEC:
            state.is_tripped = True
            state.trip_reason = f"timeout: {elapsed:.1f}s > {self.MAX_TIMEOUT_SEC}s"
            logger.warning("circuit_breaker.tripped", reason=state.trip_reason)
            return False

        if state.total_cost_cents > self.MAX_COST_CENTS:
            state.is_tripped = True
            state.trip_reason = f"cost: ${state.total_cost_cents/100:.4f} > ${self.MAX_COST_CENTS/100:.2f}"
            logger.warning("circuit_breaker.tripped", reason=state.trip_reason)
            return False

        if state.llm_tokens > self.MAX_TOKENS:
            state.is_tripped = True
            state.trip_reason = f"tokens: {state.llm_tokens} > {self.MAX_TOKENS}"
            logger.warning("circuit_breaker.tripped", reason=state.trip_reason)
            return False

        return True

    def record_cost(self, state: CircuitState, cents: float) -> None:
        state.total_cost_cents += cents
        logger.debug("circuit_breaker.cost", total_cents=round(state.total_cost_cents, 6))

    def record_tokens(self, state: CircuitState, count: int) -> None:
        state.llm_tokens += count
        logger.debug("circuit_breaker.tokens", total=state.llm_tokens)
