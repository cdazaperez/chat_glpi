"""
LLM Orchestrator for Helpdesk AI.
Handles OpenAI integration with tool calling for GLPI queries.
"""
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from openai import AsyncOpenAI, APIError, RateLimitError, APITimeoutError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from app.core.config import get_settings
from app.core.logging import get_logger, get_correlation_id
from app.models.schemas import (
    Reference,
    ReferenceType,
    SuggestedAction,
    ActionType,
    ChatMessage,
    MessageRole,
    GLPIKBArticle,
    GLPITicket,
    GLPISolution,
    GLPIFollowup,
)
from app.services.glpi_client import GLPIClient, GLPIError

logger = get_logger(__name__)


# Tool definitions for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "glpi_kb_search",
            "description": "Search the GLPI Knowledge Base for articles matching a query. Use this to find documented solutions, guides, and FAQs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - keywords, error messages, or topic to search for"
                    },
                    "category_id": {
                        "type": "integer",
                        "description": "Optional category ID to filter results"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_kb_get",
            "description": "Get the full content of a specific Knowledge Base article by ID. Use this after searching to get complete article details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kb_id": {
                        "type": "integer",
                        "description": "The Knowledge Base article ID"
                    }
                },
                "required": ["kb_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_search",
            "description": "Search for resolved/closed tickets in GLPI. Use this to find similar past issues and their solutions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - keywords, error messages, or issue description"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["solved", "closed", "resolved", "all"],
                        "description": "Filter by ticket status (default: solved)",
                        "default": "solved"
                    },
                    "category_id": {
                        "type": "integer",
                        "description": "Optional category ID to filter results"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 5)",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_get",
            "description": "Get detailed information about a specific ticket by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID"
                    }
                },
                "required": ["ticket_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_get_solution",
            "description": "Get the applied solution for a resolved ticket. Use this to understand how a similar issue was fixed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID"
                    }
                },
                "required": ["ticket_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_create",
            "description": "Create a new support ticket in GLPI. Only use this when the user explicitly requests to create a ticket. The ticket is automatically assigned to the authenticated technician.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Brief, descriptive ticket title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the issue"
                    },
                    "requester_email": {
                        "type": "string",
                        "description": "Email of the person reporting the issue"
                    },
                    "category_id": {
                        "type": "integer",
                        "description": "Category ID for the ticket"
                    },
                    "urgency": {
                        "type": "integer",
                        "description": "Urgency level (1=Very Low, 2=Low, 3=Medium, 4=High, 5=Very High)",
                        "enum": [1, 2, 3, 4, 5]
                    },
                    "impact": {
                        "type": "integer",
                        "description": "Impact level (1=Very Low, 2=Low, 3=Medium, 4=High, 5=Very High)",
                        "enum": [1, 2, 3, 4, 5]
                    }
                },
                "required": ["title", "description"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_my_tickets",
            "description": "List the authenticated user's tickets. Use this when the user asks about their own tickets, ticket status, or open cases.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["requester", "assigned", "all"],
                        "description": "Role filter: 'requester' (tickets I created), 'assigned' (tickets assigned to me), 'all' (both). Default: 'all'",
                        "default": "all"
                    },
                    "status": {
                        "type": "string",
                        "enum": ["new", "assigned", "pending", "solved", "closed", "open", "all"],
                        "description": "Status filter. 'open' means all non-resolved statuses. Default: 'all'",
                        "default": "all"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of tickets to return (default: 10)",
                        "default": 10
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_followups",
            "description": "Get all followups (updates/comments) for a specific ticket. Use this to show the ticket's activity history.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum followups to return (default: 10)",
                        "default": 10
                    }
                },
                "required": ["ticket_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_add_followup",
            "description": "Add a followup (comment/update) to a ticket. The followup is recorded under the authenticated technician's name. Use only when the user explicitly asks to add a note or update to a ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID to add the followup to"
                    },
                    "content": {
                        "type": "string",
                        "description": "The followup content/message"
                    },
                    "is_private": {
                        "type": "boolean",
                        "description": "Whether the followup is private (only visible to technicians). Default: false",
                        "default": False
                    }
                },
                "required": ["ticket_id", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "glpi_ticket_assign",
            "description": "Assign or reassign a ticket to a technician. Requires administrator privileges. Use when the user asks to assign a ticket to someone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID"
                    },
                    "technician_username": {
                        "type": "string",
                        "description": "The GLPI username (login) of the technician to assign"
                    }
                },
                "required": ["ticket_id", "technician_username"]
            }
        }
    }
]


# System prompt for the assistant
SYSTEM_PROMPT = """You are a helpful IT support assistant for SkillNet's helpdesk. Your role is to help users solve technical issues by searching the GLPI knowledge base and resolved tickets.

## Guidelines:

1. **Search Strategy**:
   - First search the Knowledge Base (KB) for documented solutions
   - If KB doesn't have sufficient information, search resolved tickets for similar issues
   - Always cite your sources with KB_ID or TICKET_ID

2. **Response Format**:
   - Start with a brief acknowledgment of the user's issue
   - Present the most relevant solution found in GLPI
   - Provide step-by-step instructions when applicable
   - Include references to sources (e.g., "Based on KB #123" or "Similar issue resolved in Ticket #456")

3. **When No Solution Found**:
   - Clearly state that no matching solution was found in GLPI
   - Ask clarifying questions to better understand the issue
   - Suggest creating a support ticket if the issue requires human intervention

4. **Safety Rules**:
   - NEVER invent or fabricate KB articles or tickets
   - NEVER share personal information (names, emails, phone numbers) from tickets
   - NEVER execute commands or make changes without explicit user consent
   - If asked for passwords, credentials, or sensitive data, politely refuse

5. **Ticket Creation & Management**:
   - Only offer to create a ticket if no solution is found
   - Require explicit user confirmation before creating any ticket
   - Summarize what will be included in the ticket before creation
   - Created tickets are automatically assigned to the authenticated technician
   - Use glpi_my_tickets to show the user their own tickets when asked
   - Use glpi_ticket_add_followup to add updates under the authenticated user's name
   - Use glpi_ticket_assign to reassign tickets (requires admin privileges)

6. **Language**:
   - Respond in the same language the user uses
   - Use clear, non-technical language when possible
   - For technical users, provide detailed technical information

Remember: Your responses must be grounded in actual GLPI data. If you're unsure, say so."""


class GuardrailViolation(Exception):
    """Exception raised when a guardrail is violated."""
    pass


class LLMOrchestrator:
    """
    Orchestrates LLM interactions with GLPI tool calling.

    Features:
    - OpenAI integration with configurable model
    - Tool calling for GLPI operations
    - Guardrails for safety
    - Response formatting with references
    """

    # Blocked patterns for guardrails
    BLOCKED_PATTERNS = [
        r"(?i)password\s+(?:is|for|of)",
        r"(?i)give\s+me\s+(?:the\s+)?(?:credentials|password|api\s*key)",
        r"(?i)delete\s+(?:all|every)",
        r"(?i)drop\s+(?:table|database)",
        r"(?i)ignore\s+(?:previous|all)\s+instructions",
        r"(?i)pretend\s+(?:you\s+are|to\s+be)",
        r"(?i)bypass\s+(?:security|authentication)",
    ]

    def __init__(self, glpi_client: GLPIClient, user_context: Optional[Dict[str, Any]] = None):
        """Initialize the orchestrator.

        Args:
            glpi_client: GLPI API client
            user_context: Authenticated user info (user_id, username, email)
        """
        self.settings = get_settings()
        self.glpi = glpi_client
        self._user_context = user_context or {}

        # Initialize OpenAI client
        client_kwargs = {
            "api_key": self.settings.openai.api_key,
            "base_url": self.settings.openai.base_url,
            "timeout": self.settings.openai.timeout_seconds,
        }

        if self.settings.openai.org_id:
            client_kwargs["organization"] = self.settings.openai.org_id

        # 'project' kwarg requires openai>=1.25.0; detect support at runtime
        if self.settings.openai.project_id:
            import inspect
            init_params = inspect.signature(AsyncOpenAI.__init__).parameters
            if "project" in init_params:
                client_kwargs["project"] = self.settings.openai.project_id
            else:
                logger.warning(
                    "OPENAI_PROJECT_ID is set but installed openai SDK does not "
                    "support the 'project' parameter. Upgrade to openai>=1.25.0."
                )

        self._client = AsyncOpenAI(**client_kwargs)
        self._references: List[Reference] = []
        self._sources_consulted: List[str] = []
        self._tokens_used: int = 0
        self._cache_hit: bool = False

    def _check_guardrails(self, message: str):
        """Check message against guardrails."""
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, message):
                logger.warning(
                    "Guardrail violation detected",
                    data={"pattern": pattern, "correlation_id": get_correlation_id()}
                )
                raise GuardrailViolation(
                    "I'm sorry, but I cannot help with that request. "
                    "If you have a legitimate IT support question, please rephrase it."
                )

    def _build_messages(
        self,
        user_message: str,
        history: Optional[List[ChatMessage]] = None
    ) -> List[Dict[str, str]]:
        """Build the messages list for the API call."""
        system_content = SYSTEM_PROMPT

        # Inject authenticated user context so the AI knows who it's helping
        if self._user_context:
            user_info_parts = []
            if self._user_context.get("username"):
                user_info_parts.append(f"Username: {self._user_context['username']}")
            if self._user_context.get("email"):
                user_info_parts.append(f"Email: {self._user_context['email']}")
            if self._user_context.get("firstname") or self._user_context.get("lastname"):
                name = f"{self._user_context.get('firstname', '')} {self._user_context.get('lastname', '')}".strip()
                user_info_parts.append(f"Name: {name}")
            if self._user_context.get("user_id"):
                user_info_parts.append(f"GLPI User ID: {self._user_context['user_id']}")
            if user_info_parts:
                system_content += (
                    "\n\n**Current authenticated user:**\n"
                    + "\n".join(f"- {p}" for p in user_info_parts)
                    + "\n\nWhen the user asks about 'my tickets' or their open cases, "
                    "use glpi_my_tickets. Ticket searches filter by this user. "
                    "Ticket creation auto-assigns to this technician. "
                    "Followups are recorded under this user's name."
                )

        messages = [{"role": "system", "content": system_content}]

        # Add conversation history
        if history:
            for msg in history[-10:]:  # Limit to last 10 messages
                messages.append({
                    "role": msg.role.value,
                    "content": msg.content
                })

        # Add current message
        messages.append({"role": "user", "content": user_message})

        return messages

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Tuple[str, bool]:
        """
        Execute a tool and return the result.

        Returns:
            Tuple of (result_string, success_flag)
        """
        logger.info(f"Executing tool: {tool_name}", data={"arguments": arguments})

        try:
            if tool_name == "glpi_kb_search":
                articles = await self.glpi.search_kb(
                    query=arguments["query"],
                    category_id=arguments.get("category_id"),
                    limit=arguments.get("limit", 5)
                )
                self._sources_consulted.append("kb")

                if not articles:
                    return "No Knowledge Base articles found matching the query.", True

                result = self._format_kb_search_results(articles)
                return result, True

            elif tool_name == "glpi_kb_get":
                article = await self.glpi.get_kb_article(arguments["kb_id"])

                if not article:
                    return f"Knowledge Base article #{arguments['kb_id']} not found.", True

                self._add_reference(ReferenceType.KB, article.id, article.name)
                result = self._format_kb_article(article)
                return result, True

            elif tool_name == "glpi_ticket_search":
                tickets = await self.glpi.search_tickets(
                    query=arguments["query"],
                    status=arguments.get("status", "solved"),
                    category_id=arguments.get("category_id"),
                    requester=self._user_context.get("username"),
                    limit=arguments.get("limit", 5)
                )
                self._sources_consulted.append("tickets")

                if not tickets:
                    return "No resolved tickets found matching the query.", True

                result = self._format_ticket_search_results(tickets)
                return result, True

            elif tool_name == "glpi_ticket_get":
                ticket = await self.glpi.get_ticket(arguments["ticket_id"])

                if not ticket:
                    return f"Ticket #{arguments['ticket_id']} not found.", True

                self._add_reference(ReferenceType.TICKET, ticket.id, ticket.name)
                result = self._format_ticket(ticket)
                return result, True

            elif tool_name == "glpi_ticket_get_solution":
                solution = await self.glpi.get_ticket_solution(arguments["ticket_id"])

                if not solution:
                    return f"No solution found for ticket #{arguments['ticket_id']}.", True

                result = self._format_solution(solution)
                return result, True

            elif tool_name == "glpi_ticket_create":
                # Auto-assign to authenticated technician
                assigned_to_id = None
                user_id_str = self._user_context.get("user_id")
                if user_id_str and user_id_str != "anonymous":
                    try:
                        assigned_to_id = int(user_id_str)
                    except (ValueError, TypeError):
                        pass

                ticket_id = await self.glpi.create_ticket(
                    title=arguments["title"],
                    description=arguments["description"],
                    requester_email=arguments.get("requester_email"),
                    category_id=arguments.get("category_id"),
                    urgency=arguments.get("urgency", 3),
                    impact=arguments.get("impact", 3),
                    assigned_to_id=assigned_to_id,
                )

                if ticket_id:
                    self._add_reference(ReferenceType.TICKET, ticket_id, arguments["title"])
                    msg = f"Ticket created successfully with ID: {ticket_id}"
                    if assigned_to_id:
                        msg += f" (assigned to {self._user_context.get('username', 'you')})"
                    return msg, True
                else:
                    return "Failed to create ticket. Please try again or contact support directly.", False

            elif tool_name == "glpi_my_tickets":
                user_id_str = self._user_context.get("user_id")
                if not user_id_str or user_id_str == "anonymous":
                    return "Cannot list tickets: user is not authenticated.", False

                try:
                    glpi_user_id = int(user_id_str)
                except (ValueError, TypeError):
                    return "Cannot list tickets: invalid user ID.", False

                tickets = await self.glpi.get_user_tickets(
                    user_id=glpi_user_id,
                    role=arguments.get("role", "all"),
                    status=arguments.get("status"),
                    limit=arguments.get("limit", 10),
                )
                self._sources_consulted.append("tickets")

                if not tickets:
                    role = arguments.get("role", "all")
                    status = arguments.get("status", "all")
                    return f"No tickets found for your user (role={role}, status={status}).", True

                result = self._format_my_tickets(tickets)
                return result, True

            elif tool_name == "glpi_ticket_followups":
                followups = await self.glpi.get_ticket_followups(
                    ticket_id=arguments["ticket_id"],
                    limit=arguments.get("limit", 10),
                )

                if not followups:
                    return f"No followups found for ticket #{arguments['ticket_id']}.", True

                result = self._format_followups(followups, arguments["ticket_id"])
                return result, True

            elif tool_name == "glpi_ticket_add_followup":
                user_id = None
                user_id_str = self._user_context.get("user_id")
                if user_id_str and user_id_str != "anonymous":
                    try:
                        user_id = int(user_id_str)
                    except (ValueError, TypeError):
                        pass

                followup_id = await self.glpi.add_ticket_followup(
                    ticket_id=arguments["ticket_id"],
                    content=arguments["content"],
                    user_id=user_id,
                    is_private=arguments.get("is_private", False),
                )

                if followup_id:
                    username = self._user_context.get("username", "the system")
                    return (
                        f"Followup added to ticket #{arguments['ticket_id']} "
                        f"(followup ID: {followup_id}, by {username})."
                    ), True
                else:
                    return f"Failed to add followup to ticket #{arguments['ticket_id']}.", False

            elif tool_name == "glpi_ticket_assign":
                # Resolve technician username to GLPI user ID
                tech_username = arguments["technician_username"]
                tech_user_id = await self.glpi.get_user_id_by_name(tech_username)

                if not tech_user_id:
                    return f"Technician '{tech_username}' not found in GLPI.", False

                success = await self.glpi.assign_ticket(
                    ticket_id=arguments["ticket_id"],
                    user_id=tech_user_id,
                    actor_type=2,  # Assigned technician
                )

                if success:
                    return (
                        f"Ticket #{arguments['ticket_id']} assigned to "
                        f"{tech_username} (user ID: {tech_user_id})."
                    ), True
                else:
                    return (
                        f"Could not assign ticket #{arguments['ticket_id']} to "
                        f"{tech_username}. The user may already be assigned, or "
                        "you may not have administrator privileges."
                    ), False

            else:
                return f"Unknown tool: {tool_name}", False

        except GLPIError as e:
            logger.error(f"GLPI error in tool {tool_name}: {e}")
            return f"Error accessing GLPI: {str(e)}", False
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Error executing {tool_name}: Unable to complete the operation.", False

    def _add_reference(self, ref_type: ReferenceType, ref_id: int, title: str):
        """Add a reference to the list."""
        # Avoid duplicates
        for ref in self._references:
            if ref.type == ref_type and ref.id == ref_id:
                return

        self._references.append(Reference(
            type=ref_type,
            id=ref_id,
            title=title
        ))

    def _format_kb_search_results(self, articles: List[GLPIKBArticle]) -> str:
        """Format KB search results for the LLM."""
        results = ["Knowledge Base search results:"]
        for article in articles:
            self._add_reference(ReferenceType.KB, article.id, article.name)
            results.append(f"\n- KB #{article.id}: {article.name}")
            if article.answer:
                # Truncate long answers
                answer = article.answer[:500] + "..." if len(article.answer) > 500 else article.answer
                # Remove HTML tags
                answer = re.sub(r'<[^>]+>', '', answer)
                results.append(f"  Summary: {answer}")
        return "\n".join(results)

    def _format_kb_article(self, article: GLPIKBArticle) -> str:
        """Format a single KB article for the LLM."""
        content = article.answer or "No content available."
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)

        return f"""Knowledge Base Article #{article.id}:
Title: {article.name}
Category: {article.category_name or 'N/A'}
Content:
{content}"""

    def _format_ticket_search_results(self, tickets: List[GLPITicket]) -> str:
        """Format ticket search results for the LLM."""
        results = ["Resolved ticket search results:"]
        for ticket in tickets:
            self._add_reference(ReferenceType.TICKET, ticket.id, ticket.name)
            results.append(f"\n- Ticket #{ticket.id}: {ticket.name}")
            results.append(f"  Status: {ticket.status_name or 'Unknown'}")
            if ticket.content:
                # Truncate and clean
                content = ticket.content[:300] + "..." if len(ticket.content) > 300 else ticket.content
                content = re.sub(r'<[^>]+>', '', content)
                # Mask potential PII
                content = self._mask_pii(content)
                results.append(f"  Description: {content}")
        return "\n".join(results)

    def _format_ticket(self, ticket: GLPITicket) -> str:
        """Format a single ticket for the LLM."""
        content = ticket.content or "No description available."
        content = re.sub(r'<[^>]+>', '', content)
        content = self._mask_pii(content)

        return f"""Ticket #{ticket.id}:
Title: {ticket.name}
Status: {ticket.status_name or 'Unknown'}
Urgency: {ticket.urgency}/5
Impact: {ticket.impact}/5
Description:
{content}"""

    def _format_solution(self, solution: GLPISolution) -> str:
        """Format a ticket solution for the LLM."""
        content = solution.content or "No solution content."
        content = re.sub(r'<[^>]+>', '', content)

        return f"""Solution for Ticket #{solution.ticket_id}:
{content}"""

    def _format_my_tickets(self, tickets: List[GLPITicket]) -> str:
        """Format user's tickets for the LLM."""
        results = [f"Your tickets ({len(tickets)} found):"]
        for ticket in tickets:
            self._add_reference(ReferenceType.TICKET, ticket.id, ticket.name)
            results.append(f"\n- Ticket #{ticket.id}: {ticket.name}")
            results.append(f"  Status: {ticket.status_name or 'Unknown'}")
            if ticket.date_creation:
                results.append(f"  Created: {ticket.date_creation}")
            if ticket.date_mod:
                results.append(f"  Last modified: {ticket.date_mod}")
        return "\n".join(results)

    def _format_followups(self, followups: List[Any], ticket_id: int) -> str:
        """Format ticket followups for the LLM."""
        results = [f"Followups for ticket #{ticket_id} ({len(followups)} entries):"]
        for fu in followups:
            results.append(f"\n- Followup #{fu.id} ({fu.date_creation or 'unknown date'}):")
            content = fu.content or ""
            content = re.sub(r'<[^>]+>', '', content)
            if len(content) > 400:
                content = content[:400] + "..."
            results.append(f"  {content}")
        return "\n".join(results)

    def _mask_pii(self, text: str) -> str:
        """Mask potential PII in text."""
        # Mask email addresses
        text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[email]', text)
        # Mask phone numbers
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[phone]', text)
        return text

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((APITimeoutError, RateLimitError)),
    )
    async def _call_openai(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None
    ) -> Any:
        """Make a call to OpenAI API with retry logic."""
        kwargs = {
            "model": self.settings.openai.model,
            "messages": messages,
            "temperature": self.settings.openai.temperature,
            "max_tokens": self.settings.openai.max_tokens,
        }

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)

        # Track token usage
        if response.usage:
            self._tokens_used += response.usage.total_tokens

        return response

    async def process_message(
        self,
        message: str,
        history: Optional[List[ChatMessage]] = None,
    ) -> Tuple[str, List[Reference], List[SuggestedAction], int]:
        """
        Process a user message and generate a response.

        Args:
            message: The user's message
            history: Optional conversation history

        Returns:
            Tuple of (response_text, references, suggested_actions, tokens_used)
        """
        start_time = time.time()
        self._references = []
        self._sources_consulted = []
        self._tokens_used = 0
        self._cache_hit = False

        # Reset GLPI client cache hit counter
        self.glpi.reset_cache_hits()

        # Check guardrails
        self._check_guardrails(message)

        logger.info(
            "Processing chat message",
            data={"message_length": len(message), "has_history": bool(history)}
        )

        # Build initial messages
        messages = self._build_messages(message, history)

        try:
            # First API call - may include tool calls
            response = await self._call_openai(messages, tools=TOOLS)
            assistant_message = response.choices[0].message

            # Process tool calls iteratively
            max_iterations = 5  # Prevent infinite loops
            iteration = 0

            while assistant_message.tool_calls and iteration < max_iterations:
                iteration += 1

                # Add assistant message to history
                messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })

                # Execute each tool call
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        arguments = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                    result, success = await self._execute_tool(tool_name, arguments)

                    # Add tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })

                # Get next response
                response = await self._call_openai(messages, tools=TOOLS)
                assistant_message = response.choices[0].message

            # Get final response text
            response_text = assistant_message.content or "I apologize, but I couldn't generate a response. Please try again."

            # Determine suggested actions
            suggested_actions = self._determine_suggested_actions(response_text)

            # Track if any GLPI results came from cache
            self._cache_hit = self.glpi.cache_hits > 0

            processing_time = int((time.time() - start_time) * 1000)
            logger.info(
                "Chat message processed",
                data={
                    "processing_time_ms": processing_time,
                    "tokens_used": self._tokens_used,
                    "references_count": len(self._references),
                    "sources": list(set(self._sources_consulted)),
                    "cache_hit": self._cache_hit,
                }
            )

            return response_text, self._references, suggested_actions, self._tokens_used

        except GuardrailViolation:
            raise
        except RateLimitError:
            logger.error("OpenAI rate limit exceeded")
            raise Exception("The AI service is currently busy. Please try again in a moment.")
        except APIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise Exception("Unable to process your request. Please try again.")
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            raise

    def _determine_suggested_actions(self, response_text: str) -> List[SuggestedAction]:
        """Determine suggested actions based on the response."""
        actions = []

        # Check if response indicates no solution found
        no_solution_indicators = [
            "no matching solution",
            "couldn't find",
            "no results",
            "not found in",
            "no knowledge base",
            "no resolved tickets",
            "crear un ticket",
            "create a ticket",
        ]

        response_lower = response_text.lower()
        if any(indicator in response_lower for indicator in no_solution_indicators):
            actions.append(SuggestedAction(
                type=ActionType.CREATE_TICKET,
                enabled=True,
                description="Create a support ticket for human assistance"
            ))

        # Check if more information is needed
        info_indicators = [
            "could you provide",
            "more information",
            "please specify",
            "what is the",
            "when did",
            "error message",
        ]

        if any(indicator in response_lower for indicator in info_indicators):
            actions.append(SuggestedAction(
                type=ActionType.REQUEST_INFO,
                enabled=True,
                description="Please provide additional details"
            ))

        return actions

    @property
    def sources_consulted(self) -> List[str]:
        """Get the list of sources consulted."""
        return list(set(self._sources_consulted))

    @property
    def cache_hit(self) -> bool:
        """Check if any GLPI results were served from cache."""
        return self._cache_hit
