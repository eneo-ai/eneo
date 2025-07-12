"""Simple event publisher for domain events."""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from intric.events.model_events import DomainEvent


class EventHandler(ABC):
    """Base class for event handlers."""
    
    @abstractmethod
    async def handle(self, event: DomainEvent) -> None:
        """Handle the domain event."""
        pass


class LoggingEventHandler(EventHandler):
    """Event handler that logs events for observability."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
    
    async def handle(self, event: DomainEvent) -> None:
        """Log the event details."""
        self.logger.info(
            f"Domain event published: {event.__class__.__name__}",
            extra={
                "event_type": event.__class__.__name__,
                "event_data": event.model_dump(),
            }
        )


class EventPublisher:
    """Simple in-memory event publisher for domain events."""
    
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = {}
        self.logger = logging.getLogger(__name__)
        # Add default logging handler
        self.register_handler("*", LoggingEventHandler(self.logger))
    
    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type or '*' for all events."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    async def publish(self, event: DomainEvent) -> None:
        """Publish a domain event to all registered handlers."""
        event_type = event.__class__.__name__
        
        # Get handlers for specific event type and wildcard handlers
        handlers = self._handlers.get(event_type, []) + self._handlers.get("*", [])
        
        if not handlers:
            self.logger.warning(f"No handlers registered for event: {event_type}")
            return
        
        # Execute all handlers concurrently
        await asyncio.gather(
            *[handler.handle(event) for handler in handlers],
            return_exceptions=True
        )
    
    async def publish_many(self, events: List[DomainEvent]) -> None:
        """Publish multiple events."""
        await asyncio.gather(
            *[self.publish(event) for event in events],
            return_exceptions=True
        )


# Global instance for simple usage
_event_publisher = EventPublisher()


def get_event_publisher() -> EventPublisher:
    """Get the global event publisher instance."""
    return _event_publisher