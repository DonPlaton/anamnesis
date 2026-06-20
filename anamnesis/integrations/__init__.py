"""Optional framework integrations for Anamnesis.

Each submodule wraps the stdlib-only `anamnesis.api` for a specific framework and is
imported explicitly so the package never hard-depends on a framework:

    from anamnesis.integrations.langchain_memory import AnamnesisRetriever, AnamnesisMemory
    from anamnesis.integrations.llamaindex_retriever import AnamnesisRetriever

Install the extra you need:  pip install anamnesis-memory[langchain]  (or [llamaindex]).
The adapters add memory to an existing agent without touching the stdlib core.
"""
