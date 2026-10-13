## Heini's working preferences

- Write formally and concisely. State conclusions with evidence and limitations.
- Confirm the actual host before making operating-system-specific changes.
  I use native Windows with PowerShell, and Arch Linux with Zsh and Hyprland.
- I work with PowerShell, Bash, Python, R, Markdown and LaTeX, in VS Code and
  Neovim. I understand statistics better than programming.
- Structure scripts with useful help, examples, explicit errors, meaningful
  comments and commented dash separators. Prefer two-space indentation and
  authored lines within 81 columns where practical.
- In Bash use `function name() { ...; }`. Quote expansions and use argument
  arrays. In PowerShell prefer approved Verb-Noun function names, comment-based
  help, parameter validation and explicit native-process exit-code checks.
- Never use eval or Invoke-Expression to assemble commands. In R prefer `=`
  for assignment. Explain non-obvious code decisions.
- For mathematical explanations, use rendered LaTeX and stepwise derivations
  when these improve understanding.
- For neuroscience and behavioral analyses, preserve the experimental unit,
  repeated-measures structure, outcome family and random-effects assumptions.
  Never silently transform data, change analyses or invent results.

## Repository work

- Read applicable AGENTS.md files, project manifests, Git status and existing
  checks before editing. Preserve unrelated work and established conventions.
- Complete authorized work and verify relevant behavior. Ask when a missing
  decision materially affects scope or new authorization is actually required.
- Use the supplied specialist agents when I ask for delegation or applicable
  project instructions request it. Assign disjoint ownership for parallel edits
  and validate the integrated result.
- For substantial tasks keep a short plan. Read an existing
  docs/codex-context.md for related work. Maintain a concise handover note there
  when useful; it is an ordinary project document, not a native memory format.
- Prefer rg and targeted reads. Run meaningful existing tests for changed
  behavior. Use the project's formatters and linters on affected files.
- Use the OpenAI documentation MCP for Codex and OpenAI questions. Use current
  primary documentation for changing software behavior.
- Inspect the diff before finishing. Report changes, actual verification and
  remaining limitations. Never describe an unperformed check as passed.
- Push, publish, send messages and make destructive system changes only when
  requested or already authorized. Prepare concrete, reviewable work first.
- Keep credentials and private research records out of instructions, memory,
  logs and Git. Correct stale context using current evidence and instructions.
