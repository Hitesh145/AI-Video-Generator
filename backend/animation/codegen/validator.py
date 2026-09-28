"""Static checks on LLM-generated Manim code. Accident protection, not a sandbox."""

import ast


ALLOWED_IMPORTS = frozenset({"manim", "math", "random", "numpy", "kit"})
FORBIDDEN_NAMES = frozenset({
    "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "input", "breakpoint", "exit", "quit",
})
FORBIDDEN_ATTRIBUTES = FORBIDDEN_NAMES | frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib", "socket", "importlib", "ctypes", "ctypeslib",
})
SCENE_CLASS = "SectionScene"


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def validate_scene_code(code: str) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError on line {exc.lineno}: {exc.msg}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", "?")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    errors.append(f"Line {line}: import of '{alias.name}' is not allowed.")
                if any(part in FORBIDDEN_ATTRIBUTES for part in alias.name.split(".")[1:]):
                    errors.append(f"Line {line}: import of '{alias.name}' is not allowed.")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or module.split(".")[0] not in ALLOWED_IMPORTS:
                errors.append(f"Line {line}: import from '{'.' * node.level}{module}' is not allowed.")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or _is_dunder(node.id):
                errors.append(f"Line {line}: use of '{node.id}' is not allowed.")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES or _is_dunder(node.attr):
                errors.append(f"Line {line}: attribute '{node.attr}' is not allowed.")

    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    if classes != [SCENE_CLASS]:
        errors.append(
            f"Code must define exactly one top-level class named {SCENE_CLASS}; found {classes or 'none'}."
        )

    return errors
