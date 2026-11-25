"""Find methods in the Java source with tree-sitter."""

import jpamb
import jvm
import tree_sitter
import tree_sitter_java

JAVA = tree_sitter.Language(tree_sitter_java.language())
PARSER = tree_sitter.Parser(JAVA)


def find_method(suite: jpamb.Suite, methodid: jvm.AbsMethodID) -> tree_sitter.Node | None:
    """The method's declaration in its source file, or None if not unique."""
    source = suite.sourcefile(methodid.classname).read_bytes()
    tree = PARSER.parse(source)
    name = methodid.extension.name
    arity = len(methodid.extension.params)

    matches = []
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "method_declaration":
            node_name = node.child_by_field_name("name")
            if node_name is not None and node_name.text.decode() == name:
                if len(parameters(node)) == arity:
                    matches.append(node)
        stack.extend(node.children)

    return matches[0] if len(matches) == 1 else None


def parameters(method: tree_sitter.Node) -> list[tree_sitter.Node]:
    params = method.child_by_field_name("parameters")
    return [c for c in params.children if c.type == "formal_parameter"]


def parameter_names(method: tree_sitter.Node) -> list[str]:
    return [p.child_by_field_name("name").text.decode() for p in parameters(method)]
