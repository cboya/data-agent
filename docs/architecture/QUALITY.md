# Quality Contract

## 1. Principle

Architecture is enforceable only when important invariants have mechanical evidence.

`task quality` is the single local quality gate.

## 2. Required quality classes

`task quality` must cover:

1. formatting;
2. linting;
3. static typing;
4. unit tests;
5. integration tests;
6. architecture/boundary tests;
7. SQL security tests;
8. contract tests.

`task eval` is separate because model-driven eval may be slower, but MVP completion requires both.

## 3. Suggested Python quality baseline

Codex may select exact tools, but keep the toolchain small.

A reasonable baseline:

- Ruff for formatting/lint;
- Pyright or mypy for static typing;
- pytest for tests.

Do not add overlapping tools without a clear need.

## 4. Architecture tests

Tests should mechanically enforce at least:

- domain contracts do not import Ollama transport types;
- LLM adapter does not own session persistence;
- query execution cannot bypass SQL guard;
- answer synthesis requires `VerificationResult.PASSED`;
- curated catalog and generated catalog paths are not conflated.
- repair cannot import retrieval/M14 layers, widen its PlannerContext, or exceed the durable
  attempt bound.

Static dependency rules may be implemented through import tests/custom lints if valuable.

## 5. Test pyramid

Prioritize:

- many deterministic contract/unit tests;
- focused MySQL integration tests;
- fewer model-dependent Golden Dataset tests.

Do not make every unit test call Ollama.

Use model test doubles for deterministic harness tests.

## 6. Failure attribution

Tests/evals should help identify the failing stage rather than only saying “answer wrong.”

Prefer explicit stage artifacts and assertions.

## 7. Definition of green

A change is locally green only when:

```bash
task quality
```

passes.

MVP release candidate is green only when:

```bash
task reset
task bootstrap
task quality
task eval
```

passes.
