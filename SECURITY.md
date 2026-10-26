# Security model

User tasks, skill files, and repository documents are untrusted input. Agents receive no tools in this scaffold. Ollama generates text only and cannot invoke host tools through this code.

A proposal is inert data. Applying it requires a matching approval issued by the active Governance object. A local process with write access can bypass application-level controls; this is not a sandbox against a hostile local user or compromised interpreter.

Implemented: safe skill IDs and path containment; exact proposal digest approval; base digest recheck; archive prior content; hash-chained audit; network only when Ollama is explicitly configured.

Not implemented: cryptographic operator identity, signed approvals, process isolation, OS-level filesystem restrictions, secret management, external immutable audit storage, or a hardened prompt-injection corpus. Do not expose to untrusted users or provide privileged tools without those controls.