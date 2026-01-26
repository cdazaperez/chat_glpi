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
    GLPITask,
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
            "name": "glpi_kb_create",
            "description": "Create a new Knowledge Base article in GLPI. Use this to document solutions, procedures, or FAQs that can help resolve similar issues in the future.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Article title - should be clear and descriptive"
                    },
                    "content": {
                        "type": "string",
                        "description": "Article content - the solution, procedure, or information to document"
                    },
                    "category_id": {
                        "type": "integer",
                        "description": "Optional category ID for the article"
                    },
                    "is_faq": {
                        "type": "boolean",
                        "description": "Whether this is a FAQ article (default: false)",
                        "default": False
                    }
                },
                "required": ["name", "content"]
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
            "name": "glpi_ticket_get_followups",
            "description": "Get the followups/comments for a ticket. Use this to see the conversation history, troubleshooting steps, and additional context about how an issue was investigated and resolved.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of followups to return (default: 10)",
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
            "name": "glpi_ticket_create",
            "description": "Create a new support ticket in GLPI. Only use this when the user explicitly requests to create a ticket.",
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
            "name": "glpi_ticket_add_followup",
            "description": "Add a followup/comment to an existing ticket. Use this to add notes, updates, or responses to a ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID to add the followup to"
                    },
                    "content": {
                        "type": "string",
                        "description": "The followup/comment content"
                    },
                    "is_private": {
                        "type": "boolean",
                        "description": "Whether the followup is private (only visible to technicians)",
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
            "name": "glpi_ticket_get_tasks",
            "description": "Get the tasks associated with a ticket. Use this to see pending work items and their status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of tasks to return (default: 10)",
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
            "name": "glpi_ticket_add_task",
            "description": "Add a task to an existing ticket. Use this to create work items or action items for a ticket.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID to add the task to"
                    },
                    "content": {
                        "type": "string",
                        "description": "The task description/content"
                    },
                    "state": {
                        "type": "integer",
                        "description": "Task state (0=Information, 1=To do, 2=Done)",
                        "enum": [0, 1, 2],
                        "default": 1
                    },
                    "is_private": {
                        "type": "boolean",
                        "description": "Whether the task is private",
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
            "name": "glpi_ticket_add_solution",
            "description": "Add a solution to a ticket. Use this to document the resolution of an issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {
                        "type": "integer",
                        "description": "The ticket ID to add the solution to"
                    },
                    "content": {
                        "type": "string",
                        "description": "The solution content - describe how the issue was resolved"
                    }
                },
                "required": ["ticket_id", "content"]
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

5. **Ticket Creation**:
   - Only offer to create a ticket if no solution is found
   - Require explicit user confirmation before creating any ticket
   - Summarize what will be included in the ticket before creation

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

    def __init__(self, glpi_client: GLPIClient):
        """Initialize the orchestrator."""
        self.settings = get_settings()
        self.glpi = glpi_client

        # Initialize OpenAI client
        client_kwargs = {
            "api_key": self.settings.openai.api_key,
            "base_url": self.settings.openai.base_url,
            "timeout": self.settings.openai.timeout_seconds,
        }

        if self.settings.openai.org_id:
            client_kwargs["organization"] = self.settings.openai.org_id

        if self.settings.openai.project_id:
            client_kwargs["project"] = self.settings.openai.project_id

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
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

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

            elif tool_name == "glpi_kb_create":
                article_id = await self.glpi.create_kb_article(
                    name=arguments["name"],
                    content=arguments["content"],
                    category_id=arguments.get("category_id"),
                    is_faq=arguments.get("is_faq", False)
                )

                if article_id:
                    self._add_reference(ReferenceType.KB, article_id, arguments["name"])
                    return f"Knowledge Base article created successfully with ID: {article_id}. Title: {arguments['name']}", True
                else:
                    return "Failed to create Knowledge Base article. Please try again or contact support.", False

            elif tool_name == "glpi_ticket_search":
                tickets = await self.glpi.search_tickets(
                    query=arguments["query"],
                    status=arguments.get("status", "solved"),
                    category_id=arguments.get("category_id"),
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

            elif tool_name == "glpi_ticket_get_followups":
                limit = arguments.get("limit", 10)
                followups = await self.glpi.get_ticket_followups(
                    arguments["ticket_id"],
                    limit=limit
                )

                if not followups:
                    return f"No followups/comments found for ticket #{arguments['ticket_id']}.", True

                result = self._format_followups(arguments["ticket_id"], followups)
                return result, True

            elif tool_name == "glpi_ticket_create":
                ticket_id = await self.glpi.create_ticket(
                    title=arguments["title"],
                    description=arguments["description"],
                    requester_email=arguments.get("requester_email"),
                    category_id=arguments.get("category_id"),
                    urgency=arguments.get("urgency", 3),
                    impact=arguments.get("impact", 3)
                )

                if ticket_id:
                    self._add_reference(ReferenceType.TICKET, ticket_id, arguments["title"])
                    return f"Ticket created successfully with ID: {ticket_id}", True
                else:
                    return "Failed to create ticket. Please try again or contact support directly.", False

            elif tool_name == "glpi_ticket_add_followup":
                followup_id = await self.glpi.add_ticket_followup(
                    ticket_id=arguments["ticket_id"],
                    content=arguments["content"],
                    is_private=arguments.get("is_private", False)
                )

                if followup_id:
                    return f"Followup added successfully to ticket #{arguments['ticket_id']} (Followup ID: {followup_id})", True
                else:
                    return f"Failed to add followup to ticket #{arguments['ticket_id']}. Please try again.", False

            elif tool_name == "glpi_ticket_get_tasks":
                limit = arguments.get("limit", 10)
                tasks = await self.glpi.get_ticket_tasks(
                    arguments["ticket_id"],
                    limit=limit
                )

                if not tasks:
                    return f"No tasks found for ticket #{arguments['ticket_id']}.", True

                result = self._format_tasks(arguments["ticket_id"], tasks)
                return result, True

            elif tool_name == "glpi_ticket_add_task":
                task_id = await self.glpi.add_ticket_task(
                    ticket_id=arguments["ticket_id"],
                    content=arguments["content"],
                    state=arguments.get("state", 1),
                    is_private=arguments.get("is_private", False)
                )

                if task_id:
                    return f"Task added successfully to ticket #{arguments['ticket_id']} (Task ID: {task_id})", True
                else:
                    return f"Failed to add task to ticket #{arguments['ticket_id']}. Please try again.", False

            elif tool_name == "glpi_ticket_add_solution":
                solution_id = await self.glpi.add_ticket_solution(
                    ticket_id=arguments["ticket_id"],
                    content=arguments["content"]
                )

                if solution_id:
                    return f"Solution added successfully to ticket #{arguments['ticket_id']} (Solution ID: {solution_id})", True
                else:
                    return f"Failed to add solution to ticket #{arguments['ticket_id']}. Please try again.", False

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

    def _format_followups(self, ticket_id: int, followups: List[GLPIFollowup]) -> str:
        """Format ticket followups for the LLM."""
        if not followups:
            return f"No followups found for ticket #{ticket_id}."

        lines = [f"Followups/Comments for Ticket #{ticket_id} ({len(followups)} entries):"]
        lines.append("-" * 50)

        for i, followup in enumerate(followups, 1):
            # Clean HTML from content
            content = followup.content or "No content."
            content = re.sub(r'<[^>]+>', '', content)
            content = self._mask_pii(content)

            date_str = followup.date_creation or "Unknown date"
            lines.append(f"\n[{i}] Date: {date_str}")
            lines.append(f"Content: {content}")
            lines.append("-" * 30)

        return "\n".join(lines)

    def _format_tasks(self, ticket_id: int, tasks: List[GLPITask]) -> str:
        """Format ticket tasks for the LLM."""
        if not tasks:
            return f"No tasks found for ticket #{ticket_id}."

        state_names = {0: "Information", 1: "To Do", 2: "Done"}
        lines = [f"Tasks for Ticket #{ticket_id} ({len(tasks)} tasks):"]
        lines.append("-" * 50)

        for i, task in enumerate(tasks, 1):
            # Clean HTML from content
            content = task.content or "No content."
            content = re.sub(r'<[^>]+>', '', content)
            content = self._mask_pii(content)

            state_str = state_names.get(task.state, "Unknown")
            date_str = task.date_creation or "Unknown date"
            lines.append(f"\n[{i}] Task ID: {task.id}")
            lines.append(f"State: {state_str}")
            lines.append(f"Date: {date_str}")
            lines.append(f"Content: {content}")
            lines.append("-" * 30)

        return "\n".join(lines)

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
