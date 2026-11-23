# Contributing

Issues and pull requests are welcome.

**The most useful issue** is a case where the Stop hook got it wrong: a shell command that wrote to a project and wasn't detected, or a read-only command that was taken for a write. Paste the command (redact paths if you need to) and what the hook did.

**Before a pull request**

```bash
uv run --with pytest python -m pytest -q tests/ andon/tests/
```

(or `python -m pytest -q tests/ andon/tests/` with pytest installed). A new behaviour comes with a test that fails without it.

**Three rules the code keeps**

1. **Zero dependencies.** The hook and Andon run on the Python that ships with the OS (3.9 and later). Tests use pytest only.
2. **The hook never blocks for its own failure.** A missing tool, a timeout or an unreadable map lets the turn end and writes one line to the log. A guard that has to be babysat is worse than no guard.
3. **Andon does the counting in code.** Recurrences, chronic causes and the held rate are computed by `andon.py`, never left to a model, and the tool refuses any write that would leave the registry wrong.
