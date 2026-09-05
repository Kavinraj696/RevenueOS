import uuid
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
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
    """
    workflow_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    merchant_id: Optional[uuid.UUID] = None
    trigger_type: str = "auto"
    trigger_id: Optional[str] = None
    current_stage: AgentWorkflowStage = AgentWorkflowStage.OBSERVE
    
    # In-memory context strictly for the current workflow execution
    memory: Dict[str, Any] = Field(default_factory=dict)
    
    # Chronological execution log
    execution_logs: List[AgentLogEntry] = Field(default_factory=list)

    def transition_to(self, next_stage: AgentWorkflowStage) -> None:
        """Advance the agent state machine to the next workflow stage."""
        self.current_stage = next_stage

    def log_tool_execution(
        self,
        tool_name: str,
        input_args: Dict[str, Any],
        output_summary: str,
        duration_ms: float = 0.0
    ) -> None:
        """Append a structured log entry of a tool execution."""
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
