"""
Pydantic models for request/response schemas.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field, field_validator
import re


class MessageRole(str, Enum):
    """Message roles in conversation."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ReferenceType(str, Enum):
    """Types of GLPI references."""
    KB = "kb"
    TICKET = "ticket"


class ActionType(str, Enum):
    """Types of suggested actions."""
    CREATE_TICKET = "create_ticket"
    ESCALATE = "escalate"
    REQUEST_INFO = "request_info"


class Reference(BaseModel):
    """A reference to a GLPI resource."""
    type: ReferenceType
    id: int
    title: str
    relevance: Optional[float] = None
    url: Optional[str] = None


class SuggestedAction(BaseModel):
    """A suggested action for the user."""
    type: ActionType
    enabled: bool = True
    description: Optional[str] = None
    prefilled: Optional[Dict[str, Any]] = None


class ChatMessage(BaseModel):
    """A single chat message."""
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    references: List[Reference] = Field(default_factory=list)


class ChatContext(BaseModel):
    """Optional context for a chat request."""
    user_email: Optional[str] = None
    department: Optional[str] = None
    user_role: Optional[str] = None


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: Optional[str] = None
    context: Optional[ChatContext] = None

    @field_validator("message")
    @classmethod
    def sanitize_message(cls, v: str) -> str:
        """Sanitize message content."""
        # Remove potential script tags
        v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
        # Remove HTML tags but keep content
        v = re.sub(r'<[^>]+>', '', v)
        # Trim whitespace
        return v.strip()


class ResponseMetadata(BaseModel):
    """Metadata for a chat response."""
    correlation_id: str
    processing_time_ms: int
    sources_consulted: List[str] = Field(default_factory=list)
    tokens_used: Optional[int] = None
    cache_hit: bool = False


class ChatResponse(BaseModel):
    """Response body for chat endpoint."""
    response: str
    session_id: str
    references: List[Reference] = Field(default_factory=list)
    suggested_actions: List[SuggestedAction] = Field(default_factory=list)
    metadata: ResponseMetadata


class TicketCreateRequest(BaseModel):
    """Request body for ticket creation."""
    title: str = Field(..., min_length=5, max_length=250)
    description: str = Field(..., min_length=10, max_length=10000)
    requester_email: Optional[str] = None
    category_id: Optional[int] = None
    urgency: Optional[int] = Field(None, ge=1, le=5)
    impact: Optional[int] = Field(None, ge=1, le=5)
    session_id: Optional[str] = None

    @field_validator("title", "description")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        """Sanitize text content."""
        v = re.sub(r'<script[^>]*>.*?</script>', '', v, flags=re.IGNORECASE | re.DOTALL)
        v = re.sub(r'<[^>]+>', '', v)
        return v.strip()


class TicketCreateResponse(BaseModel):
    """Response body for ticket creation."""
    success: bool
    ticket_id: Optional[int] = None
    ticket_url: Optional[str] = None
    message: str


class HealthStatus(BaseModel):
    """Health check response."""
    status: str
    timestamp: datetime
    version: str
    components: Dict[str, str]


class ErrorResponse(BaseModel):
    """Error response body."""
    error: str
    detail: Optional[str] = None
    correlation_id: Optional[str] = None


# GLPI Data Models

class GLPIKBArticle(BaseModel):
    """Knowledge Base article from GLPI."""
    id: int
    name: str
    answer: Optional[str] = None
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    is_faq: bool = False
    view_count: int = 0
    date_creation: Optional[datetime] = None
    date_mod: Optional[datetime] = None


class GLPITicket(BaseModel):
    """Ticket from GLPI."""
    id: int
    name: str
    content: Optional[str] = None
    status: int
    status_name: Optional[str] = None
    urgency: int = 3
    impact: int = 3
    priority: int = 3
    category_id: Optional[int] = None
    category_name: Optional[str] = None
    date_creation: Optional[datetime] = None
    date_mod: Optional[datetime] = None
    solvedate: Optional[datetime] = None
    closedate: Optional[datetime] = None


class GLPISolution(BaseModel):
    """Solution for a ticket in GLPI."""
    id: int
    ticket_id: int
    content: str
    status: int
    date_creation: Optional[datetime] = None
    user_name: Optional[str] = None


class GLPIFollowup(BaseModel):
    """Followup entry for a ticket in GLPI."""
    id: int
    ticket_id: int
    content: str
    is_private: bool = False
    date_creation: Optional[datetime] = None
    user_name: Optional[str] = None


class GLPITask(BaseModel):
    """Task entry for a ticket in GLPI."""
    id: int
    ticket_id: int
    content: str
    state: int = 1  # 0=Information, 1=To do, 2=Done
    is_private: bool = False
    date_creation: Optional[datetime] = None
    begin_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    user_name: Optional[str] = None


# Session Models

class ConversationHistory(BaseModel):
    """Conversation history for a session."""
    session_id: str
    messages: List[ChatMessage] = Field(default_factory=list)
    context: Optional[ChatContext] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# Tool Call Models (for OpenAI function calling)

class ToolCall(BaseModel):
    """Represents a tool call from OpenAI."""
    id: str
    name: str
    arguments: Dict[str, Any]


class ToolResult(BaseModel):
    """Result of a tool execution."""
    tool_call_id: str
    name: str
    content: str
    success: bool = True
    error: Optional[str] = None
