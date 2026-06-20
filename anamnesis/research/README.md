# `research/`: the honest eval lab

**Not part of the product.** Nothing here is imported by the runtime. This directory is the
measurement bench: the experiments that decided what Anamnesis ships, and, just as often,
what it *doesn't*. It exists for credibility and reproducibility, not for you to run.

The one thing that makes Anamnesis different from most "memory for agents" repos:
**we measured the clever ideas on real data and cut the ones that lost.** A memory you
can't trust is worse than no memory. The receipts are here.

## Start here

| Study | File | Verdict |
|---|---|---|
| External retrieval benchmark (LongMemEval-oracle, 940 sessions / 500 questions) | [`longmem_eval.py`](longmem_eval.py) → [`longmem_results.json`](longmem_results.json) | calibrated fusion R@5 **0.80** / R@10 **0.86**; +trained cross-encoder R@1 **0.55→0.61** |
| **Calibrated score fusion** (why we beat rank fusion and the leaders) | [`RETRIEVAL_FUSION.md`](RETRIEVAL_FUSION.md) | RRF discards score magnitudes (trails plain BM25); calibrated fusion lifts R@5 0.66→**0.80** and tops Mem0 |
| Precision: rerankers & "stronger" embedders | [`W2_PRECISION.md`](W2_PRECISION.md) | promptable LLM reranker & 4 alt embedders **lose** to bge-m3 on top-1; only a *trained* cross-encoder wins → shipped opt-in |
| Abstractive consolidation ("summarise notes into a principle") | [`CONSOLIDATION_EVAL.md`](CONSOLIDATION_EVAL.md) · [`ABSTRACTIVE.md`](ABSTRACTIVE.md) | craters recall@3 0.82→0.35 → **not shipped** |
| Token economy (does memory actually save tokens?) | [`token_ab.py`](token_ab.py) | net-negative vs a small curated context, hugely positive vs full history: honest, not a headline |
| Head-to-head vs market leaders (same stand, local Ollama) | [`head_to_head.py`](head_to_head.py) → [`head_to_head.json`](head_to_head.json) | controlled recall@k vs Mem0 et al. See [`docs/COMPARISON.md`](../../docs/COMPARISON.md) |
| Memory-poisoning guard (injection / exfiltration / destruction) | [`POISONING.md`](POISONING.md) | 0 false-positives on a 328-note vault |

## The rest

Mechanism studies (each a write-up + a runnable `.py` + a `.json`/`.png` result):
recurrence/salience ablation ([`ABLATION_RESULTS.md`](ABLATION_RESULTS.md)),
bandit online ranker ([`BANDIT.md`](BANDIT.md)),
bi-temporal point-in-time queries ([`bitemporal_ablation.py`](bitemporal_ablation.py)),
submodular forgetting ([`FORGETTING.md`](FORGETTING.md)),
longitudinal recall ([`LONGITUDINAL_BENCH.md`](LONGITUDINAL_BENCH.md)),
rare-event salience ([`RARE_EVENT.md`](RARE_EVENT.md)),
calibrated-posterior salience ([`POSTERIOR_MODEL.md`](POSTERIOR_MODEL.md)),
real-trace replay ([`REAL_TRACE.md`](REAL_TRACE.md)),
divergent retrieval ([`DIVERGENT.md`](DIVERGENT.md)),
biological-memory analogues ([`BIO_MEMORY.md`](BIO_MEMORY.md)).

## Reproduce

```bash
# 1. fetch the dataset (see data/README.md for the source + filename)
# 2. embed once, then score (fast, re-rankable from cache):
python anamnesis/research/longmem_eval.py --embed
python anamnesis/research/longmem_eval.py --save            # writes longmem_results.json
python anamnesis/research/longmem_eval.py --xrerank --save  # + the trained cross-encoder

# token economy and the head-to-head (local Ollama, no paid key):
python anamnesis/research/token_ab.py
python anamnesis/research/head_to_head.py --only=mem0 --save
```

Each `_test_*.py` here is a self-checking unit test (stdlib, mocked, no network, no GPU);
11 of them run in CI alongside the 8 core suites.

The full method (a calibrated-posterior salience stack, an online-learning ranker,
submodular forgetting, and a recurrence-bearing benchmark) is being written up for
Zenodo/arXiv.
