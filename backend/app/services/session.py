"""
Session management service for chat conversations.
"""
import uuid
from datetime import datetime
from typing import List, Optional

from app.core.logging import get_logger
from app.models.schemas import (
    ChatMessage,
    MessageRole,
    ConversationHistory,
    ChatContext,
    Reference,
)
from app.services.cache import CacheService

logger = get_logger(__name__)


class SessionService:
    """
    Manages chat session state and conversation history.

    Features:
    - Session creation and retrieval
    - Message history management
    - Context preservation
    """

    def __init__(self, cache: Optional[CacheService] = None):
        """Initialize session service."""
        self._cache = cache
        self._local_sessions: dict = {}  # Fallback if no cache

    def create_session(self, context: Optional[ChatContext] = None) -> str:
        """
        Create a new chat session.

        Args:
            context: Optional context for the session

        Returns:
            New session ID
        """
        session_id = str(uuid.uuid4())

        history = ConversationHistory(
            session_id=session_id,
            context=context,
            messages=[],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        self._local_sessions[session_id] = history

        logger.info("Session created", data={"session_id": session_id})

        return session_id

    async def get_session(self, session_id: str) -> Optional[ConversationHistory]:
        """
        Get a session by ID.

        Args:
            session_id: The session ID

        Returns:
            Session data or None if not found
        """
        # Try local cache first
        if session_id in self._local_sessions:
            return self._local_sessions[session_id]

        # Try Redis cache
        if self._cache and self._cache.is_connected:
            data = await self._cache.get_session(session_id)
            if data:
                history = ConversationHistory(**data)
                self._local_sessions[session_id] = history
                return history

        return None

    async def save_session(self, history: ConversationHistory):
        """
        Save session to cache.

        Args:
            history: The conversation history to save
        """
        history.updated_at = datetime.utcnow()
        self._local_sessions[history.session_id] = history

        if self._cache and self._cache.is_connected:
            await self._cache.set_session(
                history.session_id,
                history.model_dump(mode='json')
            )

    async def add_message(
        self,
        session_id: str,
        role: MessageRole,
        content: str,
        references: Optional[List[Reference]] = None,
    ) -> bool:
        """
        Add a message to session history.

        Args:
            session_id: The session ID
            role: Message role (user/assistant)
            content: Message content
            references: Optional references for assistant messages

        Returns:
            True if successful, False otherwise
        """
        history = await self.get_session(session_id)

        if not history:
            logger.warning(f"Session not found: {session_id}")
            return False

        message = ChatMessage(
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
            references=references or [],
        )

        history.messages.append(message)

        # Limit history size to prevent memory issues
        max_messages = 50
        if len(history.messages) > max_messages:
            history.messages = history.messages[-max_messages:]

        await self.save_session(history)

        logger.debug(
            "Message added to session",
            data={"session_id": session_id, "role": role.value}
        )

        return True

    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None
    ) -> List[ChatMessage]:
        """
        Get messages from a session.

        Args:
            session_id: The session ID
            limit: Optional limit on number of messages (most recent)

        Returns:
            List of messages
        """
        history = await self.get_session(session_id)

        if not history:
            return []

        messages = history.messages

        if limit and len(messages) > limit:
            messages = messages[-limit:]

        return messages

    async def clear_session(self, session_id: str) -> bool:
        """
        Clear a session's message history.

        Args:
            session_id: The session ID

        Returns:
            True if successful, False otherwise
        """
        history = await self.get_session(session_id)

        if not history:
            return False

        history.messages = []
        await self.save_session(history)

        logger.info("Session cleared", data={"session_id": session_id})

        return True

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session entirely.

        Args:
            session_id: The session ID

        Returns:
            True if successful, False otherwise
        """
        if session_id in self._local_sessions:
            del self._local_sessions[session_id]

        if self._cache and self._cache.is_connected:
            await self._cache.delete_session(session_id)

        logger.info("Session deleted", data={"session_id": session_id})

        return True

    async def extend_session(self, session_id: str) -> bool:
        """
        Extend a session's TTL.

        Args:
            session_id: The session ID

        Returns:
            True if successful, False otherwise
        """
        if self._cache and self._cache.is_connected:
            return await self._cache.extend_session(session_id)
        return True

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        context: Optional[ChatContext] = None
    ) -> str:
        """
        Get existing session or create a new one.

        Args:
            session_id: Optional existing session ID
            context: Optional context for new sessions

        Returns:
            Session ID (existing or new)
        """
        if session_id and session_id in self._local_sessions:
            return session_id

        return self.create_session(context)
