"""Least-privilege local capabilities. No shell, write, network, or dynamic code execution."""
from __future__ import annotations
import ast
import math
from pathlib import Path
from typing import Any


class CapabilityError(RuntimeError):
    pass


class CapabilityRegistry:
    def __init__(self, workspace: str | Path, *, max_file_bytes: int = 131072):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise CapabilityError("Workspace must be an existing directory")
        if isinstance(max_file_bytes, bool) or not isinstance(max_file_bytes, int) or max_file_bytes <= 0:
            raise CapabilityError("max_file_bytes must be a positive integer")
        self.max_file_bytes = max_file_bytes
        self._tools = {"calculator": self._calculator, "read_text_file": self._read_text_file,
                       "search_text": self._search_text}

    @property
    def descriptions(self) -> list[dict[str, str]]:
        return [
            {"name": "calculator", "description": "Evaluate bounded basic arithmetic. Arguments: {expression: string}."},
            {"name": "read_text_file", "description": "Read a UTF-8 text file within the configured workspace only. Arguments: {path: relative string}."},
            {"name": "search_text", "description": "Search text files within the configured workspace. Arguments: {query: string}."},
        ]

    def invoke(self, name: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(name, str) or name not in self._tools:
            return {"ok": False, "error": f"Capability is not allowlisted: {name!r}"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "Tool arguments must be a JSON object"}
        try:
            return {"ok": True, "result": self._tools[name](arguments)}
        except CapabilityError as exc:
            return {"ok": False, "error": str(exc)}
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            return {"ok": False, "error": f"Capability failed closed: {type(exc).__name__}"}

    def _contained_file(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative.strip():
            raise CapabilityError("path must be a non-empty relative string")
        if Path(relative).is_absolute():
            raise CapabilityError("absolute paths are not accepted; use a workspace-relative path")
        try:
            candidate = (self.workspace / relative).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise CapabilityError("Path could not be safely resolved") from exc
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise CapabilityError("Path escapes configured workspace") from exc
        if not candidate.is_file():
            raise CapabilityError("Path is not a regular file")
        if candidate.stat().st_size > self.max_file_bytes:
            raise CapabilityError(f"File exceeds {self.max_file_bytes}-byte limit")
        return candidate

    def _read_text_file(self, args: dict) -> dict:
        if set(args) != {"path"}:
            raise CapabilityError("read_text_file accepts only the 'path' argument")
        path = self._contained_file(args["path"])
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CapabilityError(f"Cannot read UTF-8 text file: {exc}") from exc
        return {"path": path.relative_to(self.workspace).as_posix(), "content": content}

    def _search_text(self, args: dict) -> dict:
        if set(args) != {"query"}:
            raise CapabilityError("search_text accepts only the 'query' argument")
        query = args["query"]
        if not isinstance(query, str) or not query.strip() or len(query) > 256:
            raise CapabilityError("query must be 1–256 characters")
        allowed_suffixes = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml"}
        matches = []
        scanned = 0
        for path in sorted(self.workspace.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                continue
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(self.workspace)
            except (OSError, ValueError):
                continue
            if resolved.stat().st_size > self.max_file_bytes:
                continue
            scanned += 1
            if scanned > 2000:
                raise CapabilityError("Workspace search file-count limit exceeded")
            try:
                lines = resolved.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for number, line in enumerate(lines, 1):
                if query.casefold() in line.casefold():
                    matches.append({"path": resolved.relative_to(self.workspace).as_posix(),
                                    "line": number, "text": line[:500]})
                    if len(matches) >= 20:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def _calculator(self, args: dict) -> dict:
        if set(args) != {"expression"}:
            raise CapabilityError("calculator accepts only the 'expression' argument")
        expression = args["expression"]
        if not isinstance(expression, str) or not expression.strip() or len(expression) > 256:
            raise CapabilityError("expression must be 1–256 characters")
        try:
            node = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise CapabilityError("Invalid arithmetic expression") from exc
        count = 0
        def evaluate(current: ast.AST, depth: int = 0) -> float | int:
            nonlocal count
            count += 1
            if count > 64 or depth > 16:
                raise CapabilityError("Expression complexity limit exceeded")
            if isinstance(current, ast.Expression):
                return evaluate(current.body, depth + 1)
            if isinstance(current, ast.Constant) and type(current.value) in (int, float):
                value = current.value
            elif isinstance(current, ast.UnaryOp) and isinstance(current.op, (ast.UAdd, ast.USub)):
                operand = evaluate(current.operand, depth + 1)
                value = operand if isinstance(current.op, ast.UAdd) else -operand
            elif isinstance(current, ast.BinOp) and isinstance(current.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
                left, right = evaluate(current.left, depth + 1), evaluate(current.right, depth + 1)
                if isinstance(current.op, ast.Pow) and abs(right) > 8:
                    raise CapabilityError("Exponent magnitude exceeds limit")
                try:
                    if isinstance(current.op, ast.Add): value = left + right
                    elif isinstance(current.op, ast.Sub): value = left - right
                    elif isinstance(current.op, ast.Mult): value = left * right
                    elif isinstance(current.op, ast.Div): value = left / right
                    elif isinstance(current.op, ast.FloorDiv): value = left // right
                    elif isinstance(current.op, ast.Mod): value = left % right
                    else: value = left ** right
                except (ArithmeticError, OverflowError) as exc:
                    raise CapabilityError(f"Arithmetic error: {exc}") from exc
            else:
                raise CapabilityError(f"Expression node is not allowed: {type(current).__name__}")
            if not isinstance(value, (int, float)) or abs(value) > 1e15 or (isinstance(value, float) and not math.isfinite(value)):
                raise CapabilityError("Arithmetic result exceeds numeric limits")
            return value
        return {"value": evaluate(node), "expression": expression}
