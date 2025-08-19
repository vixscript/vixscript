#!/usr/bin/env python3
# vixscript v1 — tiny interpreted language w/ python extensions
# features: let, print, numbers/strings, + - * / ( ), function calls, use <py_module>

import re, sys, importlib.util, pathlib

# ---------- EXTENSION DIR ----------
EXT_DIR = pathlib.Path.home() / ".vixscript/extensions"

# ========== LEXER ==========
TOKEN_SPEC = [
    ("NUMBER",   r'\d+(\.\d+)?'),
    ("STRING",   r'"([^"\\]|\\.)*"'),
    ("ID",       r'[A-Za-z_][A-Za-z0-9_]*'),
    ("OP",       r'[\+\-\*/=(),]'),
    ("NEWLINE",  r'\n'),
    ("SKIP",     r'[ \t]+'),
    ("COMMENT",  r'\#.*'),
]
MASTER_RE = re.compile("|".join(f"(?P<{n}>{p})" for n,p in TOKEN_SPEC))

class Token:
    def __init__(self, kind, value, pos):
        self.kind, self.value, self.pos = kind, value, pos
    def __repr__(self): return f"Token({self.kind},{self.value})"

def lex(src):
    tokens = []
    for m in MASTER_RE.finditer(src):
        kind = m.lastgroup
        text = m.group()
        if kind in ("SKIP","COMMENT"): continue
        if kind == "STRING":
            text = bytes(text[1:-1], "utf-8").decode("unicode_escape")
            tokens.append(Token("STRING", text, m.start()))
        elif kind == "NUMBER":
            tokens.append(Token("NUMBER", float(text) if "." in text else int(text), m.start()))
        elif kind == "ID":
            kw = {"let","print","use"}
            tokens.append(Token(text if text in kw else "ID", text, m.start()))
        elif kind == "OP":
            tokens.append(Token(text, text, m.start()))
        elif kind == "NEWLINE":
            tokens.append(Token("NEWLINE", "\n", m.start()))
    tokens.append(Token("EOF","",len(src)))
    return tokens

# ========== PARSER ==========
class Parser:
    def __init__(self, tokens):
        self.toks, self.i = tokens, 0
    def peek(self): return self.toks[self.i]
    def take(self, kind=None, value=None):
        t = self.peek()
        if (kind is not None and t.kind != kind) or (value is not None and t.value != value):
            self.err(f"expected {kind or value}, got {t.kind}:{t.value}")
        self.i += 1
        return t
    def err(self, msg):
        pos = self.peek().pos
        raise SyntaxError(f"[parse error @ {pos}] {msg}")

    def parse_program(self):
        stmts = []
        while self.peek().kind != "EOF":
            if self.peek().kind == "NEWLINE":
                self.take("NEWLINE"); continue
            stmts.append(self.parse_stmt())
            while self.peek().kind == "NEWLINE":
                self.take("NEWLINE")
        return ("block", stmts)

    def parse_stmt(self):
        t = self.peek()
        if t.kind == "let":
            self.take("let")
            name = self.take("ID").value
            self.take("=", "=")
            e = self.parse_expr()
            return ("let", name, e)
        elif t.kind == "print":
            self.take("print")
            e = self.parse_expr()
            return ("print", e)
        elif t.kind == "use":
            self.take("use")
            mod = self.take("ID").value
            return ("use", mod)
        else:
            e = self.parse_expr()
            return ("expr", e)

    def parse_expr(self):
        return self.parse_add()
    def parse_add(self):
        node = self.parse_mul()
        while self.peek().kind in {"+","-"}:
            op = self.take().kind
            rhs = self.parse_mul()
            node = ("binop", op, node, rhs)
        return node
    def parse_mul(self):
        node = self.parse_unary()
        while self.peek().kind in {"*","/"}:
            op = self.take().kind
            rhs = self.parse_unary()
            node = ("binop", op, node, rhs)
        return node
    def parse_unary(self):
        if self.peek().kind in {"+","-"}:
            op = self.take().kind
            expr = self.parse_unary()
            return ("unary", op, expr)
        return self.parse_primary()
    def parse_primary(self):
        t = self.peek()
        if t.kind == "NUMBER":
            self.take("NUMBER"); return ("num", t.value)
        if t.kind == "STRING":
            self.take("STRING"); return ("str", t.value)
        if t.kind == "ID":
            name = self.take("ID").value
            if self.peek().kind == "(":
                self.take("(")
                args = []
                if self.peek().kind != ")":
                    args.append(self.parse_expr())
                    while self.peek().kind == ",":
                        self.take(",")
                        args.append(self.parse_expr())
                self.take(")")
                return ("call", name, args)
            return ("var", name)
        if t.kind == "(":
            self.take("(")
            e = self.parse_expr()
            self.take(")")
            return e
        self.err("unexpected token in expression")

# ========== RUNTIME ==========
class Runtime:
    def __init__(self):
        self.vars = {}
        self.funcs = {}   # name -> python callable
        self.register("type", lambda x: str(type(x).__name__))

    def register(self, name, func):
        if not callable(func):
            raise TypeError("registered object must be callable")
        self.funcs[name] = func

    def register_value(self, name, value):
        self.funcs[name] = lambda: value

    def call(self, name, args):
        if name not in self.funcs:
            raise NameError(f"function not found: {name}")
        try:
            return self.funcs[name](*args)
        except TypeError as e:
            raise TypeError(f"bad args for {name}: {e}")

# ========== INTERPRETER ==========
class Interpreter:
    def __init__(self, runtime: Runtime, stdout=print):
        self.rt = runtime
        self._out = stdout

    def eval(self, node):
        kind = node[0]
        if kind == "block":
            last = None
            for s in node[1]: last = self.eval(s)
            return last
        if kind == "let":
            _, name, expr = node
            val = self.eval(expr)
            self.rt.vars[name] = val
            return val
        if kind == "print":
            _, expr = node
            val = self.eval(expr)
            self._out(val)
            return None
        if kind == "use":
            _, modname = node
            self.load_extension(modname)
            return None
        if kind == "expr":
            return self.eval(node[1])
        if kind == "num": return node[1]
        if kind == "str": return node[1]
        if kind == "var":
            name = node[1]
            if name in self.rt.vars: return self.rt.vars[name]
            raise NameError(f"undefined variable: {name}")
        if kind == "unary":
            _, op, e = node
            v = self.eval(e)
            return +v if op=="+" else -v
        if kind == "binop":
            _, op, a, b = node
            av, bv = self.eval(a), self.eval(b)
            if op == "+": return av + bv
            if op == "-": return av - bv
            if op == "*": return av * bv
            if op == "/": return av / bv
            raise RuntimeError("unknown binop")
        if kind == "call":
            _, name, args = node
            argv = [self.eval(a) for a in args]
            return self.rt.call(name, argv)
        raise RuntimeError(f"unknown node: {kind}")

    # ----- LOAD EXTENSION FROM .vixscript/extensions -----
    def load_extension(self, modname: str):
        ext_path = EXT_DIR / modname / "main.py"
        if not ext_path.exists():
            raise FileNotFoundError(f"extension '{modname}' not found at {ext_path}")

        spec = importlib.util.spec_from_file_location(modname, str(ext_path))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)

        if hasattr(mod, "load") and callable(mod.load):
            mod.load(self.rt)
        elif hasattr(mod, "EXPORTS") and isinstance(mod.EXPORTS, dict):
            for k,v in mod.EXPORTS.items():
                if callable(v): self.rt.register(k, v)
                else: self.rt.register_value(k, v)
        else:
            raise ImportError(f"extension '{modname}' missing load(runtime) or EXPORTS dict")

# ========== DRIVER ==========
def run_code(src, stdout=print):
    tokens = lex(src)
    ast = Parser(tokens).parse_program()
    rt = Runtime()
    interp = Interpreter(rt, stdout=stdout)
    return interp.eval(ast)

def run_file(path):
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    run_code(src)

def repl():
    print("vixscript REPL — Ctrl+C to exit.")
    rt = Runtime()
    interp = Interpreter(rt)
    while True:
        try:
            line = input(">>> ")
        except (EOFError, KeyboardInterrupt):
            print("\nbye"); break
        if not line.strip(): continue
        try:
            tokens = lex(line+"\n")
            ast = Parser(tokens).parse_program()
            interp.eval(ast)
        except Exception as e:
            print("error:", e)

if __name__ == "__main__":
    if len(sys.argv) == 2:
        run_file(sys.argv[1])
    else:
        repl()
