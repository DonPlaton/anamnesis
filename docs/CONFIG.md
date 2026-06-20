# Configuration reference

**You do not need this file to run Anamnesis.** Everything auto-detects (see
[QUICKSTART.md](../QUICKSTART.md)); `install.py` prints the backend it chose. This page
is the full list of knobs for when you want to tune something. Every one is optional and
has a sensible default.

Set any of these in your shell environment or in a `.env` file next to the package /
at the repo root (see [`.env.example`](../.env.example)). `ANAMNESIS_*` is the canonical
prefix; the legacy `CLAUDE_MEMORY_*` names are still read for back-compat.

> Privacy note: `ANAMNESIS_LOCAL_ONLY` / `ANAMNESIS_CLOUD_ONLY` decide which projects may
> ever touch a cloud backend. They gate **both** extraction and the cloud embedder. See
> [Privacy & data routing](#privacy--data-routing).

---

## The ten you might actually touch

These are the only vars in [`.env.example`](../.env.example). Most people set zero of them.

| Variable | Default | What it does |
|---|---|---|
| `ANAMNESIS_CLOUD` | `auto` | Cloud extraction backend: `cerebras` / `groq` / `deepseek` / `gemini` / `none` / `auto` (picks whichever key is present, else local Ollama). |
| `CEREBRAS_API_KEY` · `GROQ_API_KEY` · `DEEPSEEK_API_KEY` · `GEMINI_API_KEY` | n/a | One key enables fast off-GPU extraction. None → local Ollama. |
| `ANAMNESIS_HOME` | `~/.anamnesis` | Where the Markdown + Git store lives. |
| `ANAMNESIS_PROJECTS_ROOT` | `~/.claude/projects` | Host-agent transcript dir for the catch-up sweep. |
| `ANAMNESIS_PROJECT_ROOTS` | n/a | Extra roots whose git repos are tracked as projects (`os.pathsep`-separated). |
| `ANAMNESIS_EMBED_PROVIDER` | `ollama` | Embedder for semantic recall: `ollama` (local) / `openai` / `voyage` / `cohere` / `gemini`. |
| `ANAMNESIS_EMBED_MODEL` | per-provider | Override the embedding model (e.g. `text-embedding-3-small`). |
| `OPENAI_API_KEY` · `VOYAGE_API_KEY` · `COHERE_API_KEY` | n/a | Key for the matching cloud embedder (Gemini reuses `GEMINI_API_KEY`). |

Everything below is **advanced**: rarely needed, safe to ignore.

---

## Extraction backends (cloud LLM, with local Ollama fallback)

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_CEREBRAS_MODEL` | `gpt-oss-120b` | Cerebras model. |
| `ANAMNESIS_GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model. |
| `ANAMNESIS_DEEPSEEK_MODEL` | `deepseek-v4-flash` | DeepSeek model. |
| `ANAMNESIS_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model. |
| `CEREBRAS_URL` · `GROQ_URL` · `DEEPSEEK_URL` · `GEMINI_URL` | provider default | Override the API endpoint (self-host / proxy). |
| `ANAMNESIS_GEMINI_TIMEOUT` / `_RETRIES` / `_BACKOFF` | `60` / `2` / `2.0` | Gemini HTTP retry policy. |

## Local models (Ollama)

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_MODEL` | `qwen3:8b` | Local extraction model (fallback, or primary if no cloud key). Bigger public tags (`qwen3:14b`, `qwen3:30b-a3b`, `qwen3:32b`) extract better with more VRAM. |
| `OLLAMA_URL` | `http://127.0.0.1:11434/api/generate` | Generation endpoint. |
| `OLLAMA_EMBED_URL` | `http://127.0.0.1:11434/api/embed` | Embedding endpoint. |
| `OLLAMA_TAGS_URL` | `http://127.0.0.1:11434/api/tags` | Liveness/model-list endpoint. |
| `ANAMNESIS_TIMEOUT` / `_RETRIES` / `_RETRY_BACKOFF` | `120` / `2` / `1.5` | Ollama call retry policy. |

## Embedding / semantic recall

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_EMBED_BASE_URL` | n/a | Any OpenAI-compatible `/v1/embeddings` host (together / deepinfra / localai). |
| `ANAMNESIS_EMBED_TIMEOUT` | `20` | Per-embed HTTP timeout (s). |
| `ANAMNESIS_EMBED_PREFIX` | `0` | Enable nomic-style task prefixes (asymmetric embedders). |
| `ANAMNESIS_EMBED_DOC_PREFIX` | `search_document: ` | Doc-side prefix when enabled. |
| `ANAMNESIS_EMBED_QUERY_PREFIX` | `search_query: ` | Query-side prefix when enabled. |
| `ANAMNESIS_EMBED_QUANT` | n/a | `binary` packs the scale-index as 1-bit sign codes: 16x smaller than the float16 default, ~lossless recall (R@5 0.802 to 0.796 on LongMemEval), and a popcount scan that stays instant into six figures of notes. For very large vaults. The float32 cache is unchanged; switching just rebuilds the index. See `research/QUANTIZATION.md`. |

After switching provider/model, re-embed once: `python anamnesis/embed_index.py --rebuild`.
The cache self-invalidates: recall stays on lexical until the rebuild, never wrong.
After setting `ANAMNESIS_EMBED_QUANT`, rebuild the index once the same way.

## Retrieval & ranking

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_FUSION` | `calibrated` | The shipped ranker: calibrated score fusion (z-normalise each signal, combine magnitudes). `rrf` falls back to reciprocal rank fusion. See `research/RETRIEVAL_FUSION.md`. |
| `ANAMNESIS_FUSION_SEM_WEIGHT` | `0.5` | Dense (semantic) weight in calibrated fusion. Measured Pareto-optimal on LongMemEval. |
| `ANAMNESIS_RECUR_FUSION_BOOST` | `0.02` | Recurrence tiebreak scaled to the calibrated (0,1) score range (inert on a no-recurrence corpus). |
| `ANAMNESIS_RANKER` | `hybrid` | Legacy RRF path / signal selector: `hybrid` (RRF) / `semantic` / `lexical`. Only active when `ANAMNESIS_FUSION=rrf` or `posterior`. |
| `ANAMNESIS_SEM_WEIGHT` | `2.0` | Semantic weight in the **RRF** fusion (distinct from `ANAMNESIS_FUSION_SEM_WEIGHT`). |
| `ANAMNESIS_SIM_FLOOR` | `0.40` | Min cosine to consider a semantic hit. |
| `ANAMNESIS_RETRIEVAL_K` | `5` | Candidates returned for on-demand search. |
| `ANAMNESIS_RETRIEVAL_EMBED_TIMEOUT` | `5` | Embed timeout during retrieval (s). |
| `ANAMNESIS_CONF_FLOOR` | `0.6` | Abstention floor: below this, "no confident match". |
| `ANAMNESIS_CONFIDENT_MARGIN` | `0.15` | Margin between top-1 and top-2 to call a result confident. |
| `ANAMNESIS_NEAR_FLOOR` | `0.15` | Near-duplicate / proximity floor. |
| `ANAMNESIS_AMBIGUITY_K` | `15` | Pool size used to judge query ambiguity. |
| `ANAMNESIS_RERANK` | `0` | Cloud-judge rerank for on-demand search (opt-in). |
| `ANAMNESIS_RERANK_POOL` | `15` | First-stage pool size fed to the reranker. |
| `ANAMNESIS_XRERANK` | `0` | Trained cross-encoder rerank (opt-in; needs `[reranker]` extra). |
| `ANAMNESIS_XRERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | Cross-encoder model. |
| `ANAMNESIS_XRERANK_MAXLEN` | `512` | Cross-encoder max sequence length. |

## Recurrence / salience prior

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_ADAPTIVE_RECUR` | `1` | Adaptive recurrence scaling (inert on a no-recurrence corpus). |
| `ANAMNESIS_RECUR_BOOST` | `0.03` | Score boost per recurrence. |
| `ANAMNESIS_RECUR_RRF_BOOST` | `0.0003` | Recurrence boost inside RRF. |
| `ANAMNESIS_RESOLVED_WEIGHT` | `0.6` | Down-weight for already-resolved (superseded) notes. |

## Recall on each prompt (task-aware)

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_PROMPT_RECALL` | `1` | Recall relevant lessons on every prompt. |
| `ANAMNESIS_PROMPT_RECALL_MODE` | `smart` | `smart` / `once` / `every`. |
| `ANAMNESIS_PROMPT_RECALL_K` | `3` | Lessons injected per prompt. |
| `ANAMNESIS_PROMPT_RECALL_MAX` | `6` | Hard ceiling per session. |
| `ANAMNESIS_PROMPT_RECALL_MIN_CHARS` | `16` | Skip recall for trivially short prompts. |
| `ANAMNESIS_PROMPT_RECALL_ALIVE_TIMEOUT` | `1` | Embedder liveness ping budget (s). |
| `ANAMNESIS_PROMPT_RECALL_EMBED_TIMEOUT` | `2` | Embed budget per prompt (s). |

## Injection / context budget

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_INJECT` | `1` | Inject the project card + lessons at SessionStart. |
| `ANAMNESIS_INJECT_BUDGET_CHARS` | `2200` | Char budget for injected memory. |
| `ANAMNESIS_PROJECT_CARD` | `1` | Maintain & inject the per-project card. |
| `ANAMNESIS_CARD_MAX_ITEMS` | `5` | Max items per card section. |
| `ANAMNESIS_CONTEXT_MAX_BYTES` | `12000` | Byte cap for `Context/<project>.md`. |
| `ANAMNESIS_CONTEXT_KEEP_RECENT` | `12` | Recent entries kept verbatim before compaction. |
| `ANAMNESIS_CONTEXT_KEEP_MIN` | `3` | Minimum entries always kept. |
| `ANAMNESIS_CONTEXT_LINKS_MAX` | `60` | Max `[[wikilinks]]` tracked per context. |
| `ANAMNESIS_USER_MODEL` | `1` | Maintain the cross-project user profile. |

## Forgetting / retention

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_ARCHIVE_DAYS` | `30` | Move Sessions/ notes to Archive after N days. |
| `ANAMNESIS_TYPED_ARCHIVE_DAYS` | `90` | Archive typed notes (patterns/mistakes/decisions) after N days. |
| `ANAMNESIS_PRUNE_DAYS` | `90` | Prune horizon for stale candidates. |
| `ANAMNESIS_DECAY_HALFLIFE` | `365` | Salience half-life (days). |
| `ANAMNESIS_DECAY_FLOOR` | `0.5` | Minimum decayed salience. |
| `ANAMNESIS_MAX_LIVE_PER_PROJECT` | `0` | `0`=off; >0 archives lowest-salience excess (submodular cap). |

## Cross-project transfer

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_CROSS_PROJECT` | `1` | Surface lessons from other projects. |
| `ANAMNESIS_CROSS_K` | `2` | Max cross-project lessons. |
| `ANAMNESIS_CROSS_SIM_FLOOR` | `0.5` | Min similarity for a cross-project hit. |

## Scaling (large stores)

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_PREFILTER_LIMIT` | `600` | Past this many candidates, FTS-prefilter then cosine-rerank the top; bounds per-prompt cost. |
| `ANAMNESIS_GRAPH_HOPS` | `0` | Multi-hop graph expansion over `[[wikilinks]]` (0 = off). |
| `ANAMNESIS_RELATION_EXPAND` | `0` | Append up to N graph-connected lessons (reached by the top hits' typed relation edges) to the **SessionStart** card, so a bug also carries its fix. 0 = off (keeps injection precise + token-lean); never runs on the per-prompt path. See `docs/INTEGRATIONS.md` (entity graph). |

## Capture / sweep / ingest

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_AGENT` | `claude-code` | Agent label stamped on captured notes. |
| `ANAMNESIS_TRACK_ANY_PROJECT` | `1` | Track any git repo you work in, not just configured roots. |
| `ANAMNESIS_MAX_TRANSCRIPT` | `12000` | Max transcript chars sent to extraction. |
| `ANAMNESIS_MAX_SWEEP_BYTES` | `10485760` | Per-file cap for the `--dir` sweep / `watch` (DoS guard). |
| `ANAMNESIS_SWEEP_DAYS` | `30` | Only sweep transcripts modified in the last N days. |
| `ANAMNESIS_SWEEP_CAP` | `8` | Max transcripts processed per SessionStart catch-up. |
| `ANAMNESIS_SWEEP_CAP_END` | `25` | Max transcripts processed per SessionEnd catch-up. |
| `ANAMNESIS_WATCH_MAX_PER_CYCLE` | `40` | Max transcripts the `watch` daemon mines per poll cycle. |
| `ANAMNESIS_TRUNCATE_HEAD_FRAC` | `0.4` | Fraction of a truncated transcript kept from the head (rest from the tail). |
| `ANAMNESIS_TRUNCATE_HEAD_CHARS` | n/a | Absolute head-char override for `truncate_smart` (wins over the fraction). |
| `ANAMNESIS_ENV_FILE` | n/a | Custom `.env` location (otherwise package/repo-root only). |

## Graph (`graph.json` for code navigation)

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_PROJECT_ROOT` | (cwd) | Root the graph generator scans. |
| `ANAMNESIS_GRAPH_MAX_FILES` | `800` | File cap for graph generation. |
| `ANAMNESIS_GRAPH_MAX_BYTES` | `120000` | Byte cap for `graph.json`. |

## Privacy & data routing

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_LOCAL_ONLY` | n/a | Comma-list of projects that must NEVER use a cloud backend (extraction **and** embedder). |
| `ANAMNESIS_CLOUD_ONLY` | n/a | Fail-safe allowlist: if set, only these projects may use the cloud; every other (incl. unknown) stays local. Takes precedence over `LOCAL_ONLY`. |
| `ANAMNESIS_QUARANTINE` | `0` | Opt-in corroboration quarantine for multi-tenant stores. |
| `ANAMNESIS_QUARANTINE_CONF` | `0.95` | Confidence required to auto-release from quarantine. |

## Sync

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_GIT_PUSH` | `0` | Push the store to a remote after each commit (cross-machine sync). |

## Research / experimental

| Variable | Default | Notes |
|---|---|---|
| `ANAMNESIS_DIVERGENCE` | `0` | Divergent-retrieval experiment (off). |
| `ANAMNESIS_STALE_CHECK` | `0` | Periodic stale-note check (off by default). |
| `ANAMNESIS_DEDUP_SIM` | `0.92` | Cosine threshold for the weekly consolidation merge (sleep-time dedup). |
| `ANAMNESIS_POST_W_REL` / `_FREQ` / `_SAL` | `1.0` / `0.3` / `0.2` | Weights for the opt-in posterior ranker (`ANAMNESIS_RANKER=posterior`). |

---

*Generated against the codebase on 2026-06-20. If you find a knob that isn't here, it's
experimental and unsupported; open an issue.*
