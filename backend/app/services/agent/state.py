import uuid
import time
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field


class AgentWorkflowStage(str, Enum):
    OBSERVE = "OBSERVE"
    INVESTIGATE = "INVESTIGATE"
    DIAGNOSE = "DIAGNOSE"
    QUANTIFY = "QUANTIFY"
    RECOMMEND = "RECOMMEND"
    POLICY_CHECK = "POLICY_CHECK"
    EXECUTE_OR_APPROVE = "EXECUTE_OR_APPROVE"
    VERIFY = "VERIFY"
    REPORT = "REPORT"
    FAILED = "FAILED"


class InvalidStateTransitionError(Exception):
    """Raised when an illegal state transition or state jumping is attempted."""
    pass


class AgentLoopDetectedError(Exception):
    """Raised when the agent exceeds maximum state transitions or tool call loops."""
    pass


# Deterministic transition table enforcing sequential progression
VALID_STAGE_TRANSITIONS: Dict[AgentWorkflowStage, Set[AgentWorkflowStage]] = {
    AgentWorkflowStage.OBSERVE: {
        AgentWorkflowStage.OBSERVE,  # Idempotent initialization
        AgentWorkflowStage.INVESTIGATE,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.INVESTIGATE: {
        AgentWorkflowStage.DIAGNOSE,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.DIAGNOSE: {
        AgentWorkflowStage.QUANTIFY,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.QUANTIFY: {
        AgentWorkflowStage.RECOMMEND,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.RECOMMEND: {
        AgentWorkflowStage.POLICY_CHECK,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.POLICY_CHECK: {
        AgentWorkflowStage.EXECUTE_OR_APPROVE,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.EXECUTE_OR_APPROVE: {
        AgentWorkflowStage.VERIFY,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.VERIFY: {
        AgentWorkflowStage.REPORT,
        AgentWorkflowStage.FAILED
    },
    AgentWorkflowStage.REPORT: {
        # Terminal state - no progression
    },
    AgentWorkflowStage.FAILED: {
        # Terminal error state
    }
}


class AgentLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    stage: str
    tool_name: str
    input_args: Dict[str, Any] = Field(default_factory=dict)
    output_summary: str
    duration_ms: float = 0.0


class AgentState(BaseModel):
    """
    Structured execution state for the RevenueOS AI Recovery Agent.
    Enforces isolation: memory is strictly kept for the active workflow run.
    Guarantees strict sequential transitions and loop protection.
    """
    workflow_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    agent_run_id: Optional[uuid.UUID] = None
    merchant_id: Optional[uuid.UUID] = None
    trigger_type: str = "auto"
    trigger_id: Optional[str] = None
    causal_trace_id: str = Field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}")
    current_stage: AgentWorkflowStage = AgentWorkflowStage.OBSERVE
    
    # In-memory context strictly for the current workflow execution
    memory: Dict[str, Any] = Field(default_factory=dict)
    
    # Chronological execution log
    execution_logs: List[AgentLogEntry] = Field(default_factory=list)

    # Loop and failure protection
    transition_count: int = 0
    max_transitions: int = 25
    tool_call_count: int = 0
    max_tool_calls: int = 40
    is_failed: bool = False
    failure_reason: Optional[str] = None

    @property
    def stage(self) -> AgentWorkflowStage:
        """Convenience alias for current_stage."""
        return self.current_stage

    def transition_to(self, next_stage: AgentWorkflowStage) -> None:
        """
        Advance the agent state machine to the next workflow stage.
        Enforces valid forward progression and forbids state jumping.
        """
        if self.is_failed and next_stage != AgentWorkflowStage.FAILED:
            raise InvalidStateTransitionError(
                f"Agent is in FAILED terminal state ({self.failure_reason}). Cannot transition to {next_stage.value}."
            )

        if self.transition_count >= self.max_transitions:
            self.fail("Exceeded maximum allowed state transitions (loop protection).")
            raise AgentLoopDetectedError(
                f"Loop protection triggered: State transitions exceeded {self.max_transitions}."
            )

        allowed = VALID_STAGE_TRANSITIONS.get(self.current_stage, set())
        if next_stage not in allowed:
            raise InvalidStateTransitionError(
                f"Illegal state jump: Cannot transition from {self.current_stage.value} to {next_stage.value}. "
                f"Allowed transitions: {[s.value for s in allowed]}."
            )

        self.current_stage = next_stage
        self.transition_count += 1

    def fail(self, reason: str) -> None:
        """Mark agent execution as failed and transition to FAILED state."""
        self.is_failed = True
        self.failure_reason = reason
        self.current_stage = AgentWorkflowStage.FAILED

    def log_tool_execution(
        self,
        tool_name: str,
        input_args: Dict[str, Any],
        output_summary: str,
        duration_ms: float = 0.0
    ) -> None:
        """Append a structured log entry of a tool execution with loop protection."""
        self.tool_call_count += 1
        if self.tool_call_count > self.max_tool_calls:
            self.fail(f"Tool call limit ({self.max_tool_calls}) exceeded.")
            raise AgentLoopDetectedError(
                f"Loop protection triggered: Tool calls exceeded limit of {self.max_tool_calls}."
            )

        entry = AgentLogEntry(
            stage=self.current_stage.value,
            tool_name=tool_name,
            input_args=input_args,
            output_summary=output_summary,
            duration_ms=duration_ms
        )
        self.execution_logs.append(entry)

    def clear_memory(self) -> None:
        """Wipe current-workflow memory upon workflow completion."""
        self.memory.clear()
