"""
No-op memory stubs for integration.
Disables ChromaDB/embedding which requires provider-specific embedding APIs
that DeepSeek and other LLM-only providers don't support.
"""

import os
import logging
from typing import Dict, Optional, List, Any

logger = logging.getLogger('agents.utils.memory')
logger.info("ℹ️ Using no-op memory stubs (ChromaDB disabled)")


class ChromaDBManager:
    """No-op ChromaDB manager."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_or_create_collection(self, name: str):
        return None


class FinancialSituationMemory:
    """No-op memory - stores nothing, returns nothing."""
    
    def __init__(self, memory_name="default", config=None):
        self.memory_name = memory_name
        self.config = config or {}

    def get_memories(self, situation, n_matches=2) -> str:
        """Called by agents to get past memories for context."""
        return ""

    def query_similar_situations(self, condition_key, k=5) -> List:
        return []

    def store_trade_result(self, company, key, result):
        pass

    def store_situation(self, company, key, situation):
        pass

    def store_position(self, company, key, position):
        pass

    def get_recent_reflections(self, company, k=5) -> List:
        return []

    def get_reflection(self, company) -> Optional[str]:
        return None

    def store_reflection(self, company, reflection):
        pass


class Matcher:
    """No-op matcher."""
    def get_best_match(self, key, situations):
        return None
