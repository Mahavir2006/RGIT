class IntelligenceError(Exception):
    """Base intelligence-layer error."""


class InvalidAgentOutput(IntelligenceError):
    """Agent returned IDs or fields that fail validation."""


class GraphUnavailableError(IntelligenceError):
    """Neo4j or graph repository is unavailable."""


class ConcurrentUpdateError(IntelligenceError):
    """Incident version conflict between concurrent workflow runs."""


class LlmTimeoutError(IntelligenceError):
    """LLM call exceeded the configured timeout."""
