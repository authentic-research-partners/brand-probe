"""Keep the Vibe Sentinel-style dependency direction explicit."""

import ast
from pathlib import Path

LAYERS = {
    "exceptions": 0,
    "schemas": 1,
    "config": 1,
    "db.connection": 1,
    "templates": 2,
    "fixtures": 2,
    "llm": 2,
    "measure": 2,
    "db.store": 2,
    "planning": 3,
    "analyze": 3,
    "engine": 4,
    "report": 4,
    "cli": 5,
    "__main__": 5,
    "web": 5,
    "__init__": 5,
    "db.__init__": 5,
}


def test_modules_obey_layers_and_no_cycles():
    modules = {
        str(p.relative_to("brandprobe").with_suffix("")).replace("/", "."): p
        for p in Path("brandprobe").rglob("*.py")
    }
    assert modules.keys() == LAYERS.keys(), "Declare the layer of every new module."
    edges = {name: set() for name in modules}
    for name, path in modules.items():
        for node in ast.walk(ast.parse(path.read_text())):
            imported = []
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "brandprobe":
                    imported = [alias.name for alias in node.names]
                elif node.module.startswith("brandprobe."):
                    suffix = node.module.removeprefix("brandprobe.")
                    imported = (
                        [suffix]
                        if suffix in modules
                        else [suffix + "." + a.name for a in node.names]
                    )
            elif isinstance(node, ast.Import):
                imported = [
                    a.name.removeprefix("brandprobe.")
                    for a in node.names
                    if a.name.startswith("brandprobe.")
                ]
            for target in imported:
                if target in modules:
                    assert LAYERS[target] <= LAYERS[name], (
                        f"{name} imports upward into {target}"
                    )
                    edges[name].add(target)

    def visit(name, stack):
        assert name not in stack, f"Dependency cycle: {stack} -> {name}"
        for target in edges[name]:
            visit(target, stack + [name])

    for name in modules:
        visit(name, [])
