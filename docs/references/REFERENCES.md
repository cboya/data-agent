# External References

These references inform the handoff. Repository contracts and tests remain the implementation source of truth.

## Codex / harness engineering

- OpenAI — Harness engineering: leveraging Codex in an agent-first world
  https://openai.com/index/harness-engineering/

Relevant repository-design lessons used here:

- repository knowledge as system of record;
- short `AGENTS.md` as a map rather than a giant manual;
- execution plans as first-class artifacts;
- mechanically enforced architecture/invariants;
- agent-friendly feedback loops.

## Ollama

- Ollama API — Chat
  https://docs.ollama.com/api/chat

- Ollama API — Embed
  https://docs.ollama.com/api/embed

- Ollama — Structured Outputs
  https://docs.ollama.com/capabilities/structured-outputs

The current local API supports:

- `POST /api/chat`;
- `POST /api/embed`;
- chat `format` as JSON or JSON Schema.

Verify behavior against the installed Ollama version during bootstrap.

## OpenAI-compatible REST profile

- Official OpenAI API reference — Chat Completions
  https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions

- Official OpenAI API reference — Embeddings
  https://developers.openai.com/api/reference/ruby/resources/embeddings/methods/create

M16 uses these wire shapes as one narrow conformance baseline and still performs local contract,
identity, size, timeout, and vector validation. “OpenAI-compatible” does not imply support for
every vendor extension or omission.

## MySQL

- MySQL 8.4 Reference Manual — Privileges Provided by MySQL
  https://dev.mysql.com/doc/refman/8.4/en/privileges-provided.html

- MySQL 8.4 Reference Manual — Server System Variables
  https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html

Use MySQL permissions plus deterministic application guards for defense in depth.
