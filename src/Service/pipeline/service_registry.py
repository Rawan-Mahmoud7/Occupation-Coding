"""
Service Registry Module.
Dependency Injection container wiring concrete implementations to interface protocols.
Single wiring point in the entire application.
"""

from dataclasses import dataclass
from sqlalchemy.ext.asyncio import async_sessionmaker

from config import Settings
from Service.interfaces.base_normalizer import Normalizer
from Service.interfaces.base_classifier import EducationClassifier
from Service.interfaces.base_rule_engine import RuleEngine
from Service.interfaces.base_cache import CacheProvider
from Service.interfaces.base_matcher import ExactMatcher
from Service.interfaces.base_embedder import Embedder
from Service.interfaces.base_llm import LLMClient
from Service.interfaces.base_retriever import Retriever

from Service.implementations.arabic_normalizer import ArabicNormalizer
from Service.implementations.education_classifier import ISCOEducationClassifier
from Service.implementations.isco_rule_engine import ISCORuleEngine
from Service.implementations.memory_cache import InMemoryCache
from Service.implementations.db_exact_matcher import DBExactMatcher
from Service.implementations.voyage_embedder import VoyageEmbedder
from Service.implementations.remote_llm import RemoteLLMClient
from Service.implementations.pgvector_retriever import PgvectorRetriever


@dataclass
class ServiceRegistry:
    """Holds instances of all core services conforming to interface protocols."""
    normalizer: Normalizer
    classifier: EducationClassifier
    rule_engine: RuleEngine
    cache: CacheProvider
    matcher: ExactMatcher
    embedder: Embedder
    llm: LLMClient
    retriever: Retriever


def build_default_registry(settings: Settings, db_session_factory: async_sessionmaker) -> ServiceRegistry:
    """Constructs and returns the ServiceRegistry with default concrete implementations."""
    return ServiceRegistry(
        normalizer=ArabicNormalizer(),
        classifier=ISCOEducationClassifier(),
        rule_engine=ISCORuleEngine(),
        cache=InMemoryCache(
            threshold=settings.SEMANTIC_CACHE_THRESHOLD,
            max_size=settings.CACHE_MAX_SIZE,
        ),
        matcher=DBExactMatcher(db_session_factory),
        embedder=VoyageEmbedder(
            api_key=settings.VOYAGE_API_KEY,
            model=settings.VOYAGE_MODEL,
            dimension=settings.VOYAGE_DIMENSION,
            rpm_limit=settings.VOYAGE_RPM_LIMIT,
            tpm_limit=settings.VOYAGE_TPM_LIMIT,
            timeout=settings.VOYAGE_TIMEOUT_SECONDS,
            max_retries=settings.VOYAGE_MAX_RETRIES,
        ),
        llm=RemoteLLMClient(
            base_url=settings.LLM_BASE_URL,
            api_keys=settings.api_keys_list,
            model=settings.LLM_MODEL,
            concurrency=settings.LLM_CONCURRENCY,
            temperature=settings.LLM_TEMPERATURE,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_tokens_per_key=settings.LLM_MONTHLY_TOKEN_QUOTA_PER_KEY,
        ),
        retriever=PgvectorRetriever(db_session_factory),
    )
