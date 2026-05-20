"""Real building-code retrieval library.

Replaces the hardcoded BUILDING_CODES_DB lookup in services/code_database.py
with BM25 lexical retrieval over actual code text. Findings emitted by the
department agents are now grounded in verbatim code chunks and the cited
section numbers are verified against the corpus before being returned.

Public surface:
    - get_corpus()       -> singleton CodeCorpus
    - get_retriever()    -> singleton CodeRetriever bound to corpus
    - CodeChunk          -> Pydantic model for a single section/chunk
"""
from app.code_library.corpus_loader import CodeChunk, get_corpus, get_retriever
from app.code_library.adapter import CorpusCodeSource, chunk_to_requirement

__all__ = ["CodeChunk", "get_corpus", "get_retriever", "CorpusCodeSource", "chunk_to_requirement"]
