"""Recursive-descent parser: SQL text -> AST (``minidb.nodes``)."""
from __future__ import annotations

from typing import Optional

from minidb import nodes as n
from minidb.lexer import EOF, IDENT, INTEGER, KEYWORD, OP, REAL, STRING, Token, tokenize
from minidb.protocol import SQLSyntaxError

TYPE_NAMES = {"integer": "INTEGER", "int": "INTEGER", "real": "REAL", "text": "TEXT",
              "boolean": "BOOLEAN", "bool": "BOOLEAN"}

_COMPARISON_OPS = ("=", "<>", "!=", "<", "<=", ">", ">=")


def parse(sql: str) -> n.Statement:
    return Parser(tokenize(sql)).parse_statement()


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.i = 0

    # ------------------------------------------------------------ token helpers

    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def peek(self, offset: int = 1) -> Token:
        return self.tokens[min(self.i + offset, len(self.tokens) - 1)]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != EOF:
            self.i += 1
        return tok

    def error(self, expected: str) -> SQLSyntaxError:
        return SQLSyntaxError(f"expected {expected}, found {self.tok.describe()}")

    def accept_keyword(self, *words: str) -> Optional[str]:
        if self.tok.is_keyword(*words):
            return self.advance().value
        return None

    def expect_keyword(self, word: str) -> None:
        if not self.accept_keyword(word):
            raise self.error(word)

    def accept_op(self, *ops: str) -> Optional[str]:
        if self.tok.is_op(*ops):
            return self.advance().value
        return None

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            raise self.error(f"'{op}'")

    def expect_ident(self, what: str = "identifier") -> str:
        if self.tok.kind != IDENT:
            if self.tok.kind == KEYWORD:
                raise SQLSyntaxError(
                    f"expected {what}, found reserved word {self.tok.value} "
                    "(reserved words cannot be used as names)")
            raise self.error(what)
        return self.advance().value

    def expect_end(self) -> None:
        if self.tok.kind != EOF:
            raise SQLSyntaxError(f"unexpected {self.tok.describe()}")

    # ------------------------------------------------------------ statements

    def parse_statement(self) -> n.Statement:
        tok = self.tok
        if tok.is_keyword("SELECT"):
            stmt = self.parse_query()
        elif tok.is_keyword("CREATE"):
            stmt = self.parse_create()
        elif tok.is_keyword("DROP"):
            stmt = self.parse_drop()
        elif tok.is_keyword("INSERT"):
            stmt = self.parse_insert()
        elif tok.is_keyword("UPDATE"):
            stmt = self.parse_update()
        elif tok.is_keyword("DELETE"):
            stmt = self.parse_delete()
        else:
            raise SQLSyntaxError(f"unsupported or malformed statement starting with "
                                 f"{tok.describe()}")
        self.expect_end()
        return stmt

    def parse_create(self) -> n.CreateTable:
        self.expect_keyword("CREATE")
        self.expect_keyword("TABLE")
        if_not_exists = False
        if self._at_if(("NOT", "EXISTS")):
            self.advance()
            self.advance()
            self.advance()
            if_not_exists = True
        name = self.expect_ident("table name")
        self.expect_op("(")
        columns = [self.parse_column_def()]
        while self.accept_op(","):
            columns.append(self.parse_column_def())
        self.expect_op(")")
        if sum(c.primary_key for c in columns) > 1:
            raise SQLSyntaxError("a table can have only one PRIMARY KEY column")
        return n.CreateTable(name, columns, if_not_exists)

    def _at_if(self, words: tuple[str, ...]) -> bool:
        """At ``IF <words>``? (IF is not reserved, so a table may be called ``if``.)"""
        if self.tok.kind != IDENT or self.tok.value != "if":
            return False
        return all(self.peek(k).is_keyword(w) for k, w in enumerate(words, start=1))

    def parse_type_name(self) -> str:
        if self.tok.kind != IDENT or self.tok.value not in TYPE_NAMES:
            raise self.error("a type name (INTEGER, REAL, TEXT or BOOLEAN)")
        return TYPE_NAMES[self.advance().value]

    def parse_column_def(self) -> n.ColumnDef:
        name = self.expect_ident("column name")
        col = n.ColumnDef(name, self.parse_type_name())
        seen: set[str] = set()

        def once(clause: str) -> None:
            if clause in seen:
                raise SQLSyntaxError(f"{clause} given twice for column {name}")
            seen.add(clause)

        while True:
            if self.accept_keyword("PRIMARY"):
                self.expect_keyword("KEY")
                once("PRIMARY KEY")
                col.primary_key = True
            elif self.accept_keyword("NOT"):
                self.expect_keyword("NULL")
                once("NOT NULL")
                col.not_null = True
            elif self.accept_keyword("UNIQUE"):
                once("UNIQUE")
                col.unique = True
            elif self.accept_keyword("DEFAULT"):
                once("DEFAULT")
                col.has_default = True
                col.default = self.parse_default_literal()
            else:
                return col

    def parse_default_literal(self) -> object:
        tok = self.tok
        if tok.is_op("-"):
            self.advance()
            if self.tok.kind not in (INTEGER, REAL):
                raise self.error("number after '-'")
            return -self.advance().value
        if tok.kind in (INTEGER, REAL, STRING):
            return self.advance().value
        if tok.is_keyword("TRUE", "FALSE", "NULL"):
            self.advance()
            return {"TRUE": True, "FALSE": False, "NULL": None}[tok.value]
        raise self.error("literal DEFAULT value")

    def parse_drop(self) -> n.DropTable:
        self.expect_keyword("DROP")
        self.expect_keyword("TABLE")
        if_exists = False
        if self._at_if(("EXISTS",)):
            self.advance()
            self.advance()
            if_exists = True
        return n.DropTable(self.expect_ident("table name"), if_exists)

    def parse_insert(self) -> n.Insert:
        self.expect_keyword("INSERT")
        self.expect_keyword("INTO")
        table = self.expect_ident("table name")
        columns = None
        if self.accept_op("("):
            columns = [self.expect_ident("column name")]
            while self.accept_op(","):
                columns.append(self.expect_ident("column name"))
            self.expect_op(")")
            dup = _first_duplicate(columns)
            if dup is not None:
                raise SQLSyntaxError(f"column {dup} listed twice in INSERT")
        if self.tok.is_keyword("SELECT"):
            return n.Insert(table, columns, None, self.parse_query())
        self.expect_keyword("VALUES")
        rows = [self.parse_value_tuple()]
        while self.accept_op(","):
            rows.append(self.parse_value_tuple())
        return n.Insert(table, columns, rows)

    def parse_value_tuple(self) -> list[n.Expr]:
        self.expect_op("(")
        values = [self.parse_expr()]
        while self.accept_op(","):
            values.append(self.parse_expr())
        self.expect_op(")")
        return values

    def parse_update(self) -> n.Update:
        self.expect_keyword("UPDATE")
        table = self.expect_ident("table name")
        self.expect_keyword("SET")
        assignments = [self.parse_assignment()]
        while self.accept_op(","):
            assignments.append(self.parse_assignment())
        dup = _first_duplicate([a[0] for a in assignments])
        if dup is not None:
            raise SQLSyntaxError(f"column {dup} assigned twice in UPDATE")
        where = self.parse_expr() if self.accept_keyword("WHERE") else None
        return n.Update(table, assignments, where)

    def parse_assignment(self) -> tuple[str, n.Expr]:
        col = self.expect_ident("column name")
        self.expect_op("=")
        return col, self.parse_expr()

    def parse_delete(self) -> n.Delete:
        self.expect_keyword("DELETE")
        self.expect_keyword("FROM")
        table = self.expect_ident("table name")
        where = self.parse_expr() if self.accept_keyword("WHERE") else None
        return n.Delete(table, where)

    # ------------------------------------------------------------ SELECT

    def parse_query(self) -> n.Query:
        """A SELECT or a set operation, with an optional trailing ORDER BY / LIMIT."""
        query = self.parse_intersect()
        while self.tok.is_keyword("UNION", "EXCEPT"):
            op = self.advance().value
            all_ = bool(self.accept_keyword("ALL"))
            if all_ and op != "UNION":
                raise SQLSyntaxError(f"{op} ALL is not supported")
            query = n.Compound(op, all_, query, self.parse_intersect())
        if self.accept_keyword("ORDER"):
            if isinstance(query, n.Select) and query.from_ is None:
                raise SQLSyntaxError("ORDER BY requires FROM")
            self.expect_keyword("BY")
            query.order_by.append(self.parse_order_item())
            while self.accept_op(","):
                query.order_by.append(self.parse_order_item())
        if self.accept_keyword("LIMIT"):
            if isinstance(query, n.Select) and query.from_ is None:
                raise SQLSyntaxError("LIMIT requires FROM")
            query.limit = self.parse_count("LIMIT")
            if self.accept_keyword("OFFSET"):
                query.offset = self.parse_count("OFFSET")
        return query

    def parse_intersect(self) -> n.Query:
        query: n.Query = self.parse_select()
        while self.accept_keyword("INTERSECT"):
            if self.tok.is_keyword("ALL"):
                raise SQLSyntaxError("INTERSECT ALL is not supported")
            query = n.Compound("INTERSECT", False, query, self.parse_select())
        return query

    def parse_select(self) -> n.Select:
        """One SELECT, without ORDER BY / LIMIT (``parse_query`` handles those)."""
        self.expect_keyword("SELECT")
        sel = n.Select(distinct=bool(self.accept_keyword("DISTINCT")), items=[])
        sel.items.append(self.parse_select_item())
        while self.accept_op(","):
            sel.items.append(self.parse_select_item())
        if not self.accept_keyword("FROM"):
            return sel  # without FROM, only DISTINCT is allowed: the caller expects the end
        sel.from_ = self.parse_from()
        if self.accept_keyword("WHERE"):
            sel.where = self.parse_expr()
        if self.accept_keyword("GROUP"):
            self.expect_keyword("BY")
            sel.group_by.append(self.parse_group_item())
            while self.accept_op(","):
                sel.group_by.append(self.parse_group_item())
        if self.accept_keyword("HAVING"):
            sel.having = self.parse_expr()
        return sel

    def parse_count(self, clause: str) -> int:
        if self.tok.kind != INTEGER:
            raise self.error(f"non-negative integer literal after {clause}")
        return self.advance().value

    def parse_select_item(self):
        if self.accept_op("*"):
            return n.Star(None)
        if self.tok.kind == IDENT and self.peek().is_op(".") and self.peek(2).is_op("*"):
            table = self.advance().value
            self.advance()
            self.advance()
            return n.Star(table)
        expr = self.parse_expr()
        alias = self.expect_ident("column alias") if self.accept_keyword("AS") else None
        return n.SelectItem(expr, alias)

    def parse_group_item(self) -> n.ColumnRef:
        expr = self.parse_expr()
        if not isinstance(expr, n.ColumnRef):
            raise SQLSyntaxError("GROUP BY items must be column references")
        return expr

    def parse_order_item(self) -> n.OrderItem:
        start = self.i
        expr = self.parse_expr()
        bare = self.i - start == 1
        desc = False
        word = self.accept_keyword("ASC", "DESC")
        if word == "DESC":
            desc = True
        return n.OrderItem(expr, desc, bare)

    def parse_from(self) -> n.FromClause:
        clause = n.FromClause(self.parse_table_ref())
        while True:
            if self.accept_keyword("CROSS"):
                self.expect_keyword("JOIN")
                clause.joins.append(n.Join("CROSS", self.parse_table_ref(), None))
                continue
            if self.accept_keyword("LEFT"):
                self.accept_keyword("OUTER")
                self.expect_keyword("JOIN")
                kind = "LEFT"
            elif self.accept_keyword("INNER"):
                self.expect_keyword("JOIN")
                kind = "INNER"
            elif self.accept_keyword("JOIN"):
                kind = "INNER"
            elif self.tok.is_keyword("RIGHT", "FULL"):
                raise SQLSyntaxError(f"{self.tok.value} JOIN is not supported")
            elif self.tok.is_op(","):
                raise SQLSyntaxError("comma-separated FROM lists are not supported; use JOIN")
            else:
                return clause
            table = self.parse_table_ref()
            self.expect_keyword("ON")
            clause.joins.append(n.Join(kind, table, self.parse_expr()))

    def parse_table_ref(self) -> n.TableRef:
        if self.accept_op("("):
            if not self.tok.is_keyword("SELECT"):
                raise self.error("SELECT in a derived table")
            query = self.parse_query()
            self.expect_op(")")
            self.accept_keyword("AS")
            if self.tok.kind != IDENT:
                raise SQLSyntaxError("a derived table requires an alias")
            return n.TableRef(None, self.advance().value, query)
        name = self.expect_ident("table name")
        alias = None
        if self.accept_keyword("AS"):
            alias = self.expect_ident("table alias")
        elif self.tok.kind == IDENT:
            alias = self.advance().value
        return n.TableRef(name, alias)

    # ------------------------------------------------------------ expressions

    def parse_expr(self) -> n.Expr:
        left = self.parse_and()
        while self.accept_keyword("OR"):
            left = n.Binary("OR", left, self.parse_and())
        return left

    def parse_and(self) -> n.Expr:
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = n.Binary("AND", left, self.parse_not())
        return left

    def parse_not(self) -> n.Expr:
        if self.accept_keyword("NOT"):
            return n.Not(self.parse_not())
        return self.parse_comparison()

    def _at_comparison(self) -> bool:
        tok = self.tok
        if tok.is_op(*_COMPARISON_OPS) or tok.is_keyword("IS", "BETWEEN", "IN", "LIKE"):
            return True
        return tok.is_keyword("NOT") and self.peek().is_keyword("BETWEEN", "IN", "LIKE")

    def parse_comparison(self) -> n.Expr:
        left = self.parse_concat()
        if not self._at_comparison():
            return left
        tok = self.advance()
        if tok.kind == OP:
            op = "<>" if tok.value == "!=" else tok.value
            result: n.Expr = n.Binary(op, left, self.parse_concat())
        elif tok.value == "IS":
            negated = bool(self.accept_keyword("NOT"))
            self.expect_keyword("NULL")
            result = n.IsNull(left, negated)
        else:
            negated = False
            if tok.value == "NOT":
                negated = True
                tok = self.advance()
            if tok.value == "BETWEEN":
                low = self.parse_concat()
                self.expect_keyword("AND")
                result = n.Between(left, low, self.parse_concat(), negated)
            elif tok.value == "IN":
                self.expect_op("(")
                if self.tok.is_keyword("SELECT"):
                    query = self.parse_query()
                    self.expect_op(")")
                    result = n.InSubquery(left, query, negated)
                    if self._at_comparison():
                        raise SQLSyntaxError("comparison operators are non-associative; "
                                             "use parentheses")
                    return result
                items = [self.parse_expr()]
                while self.accept_op(","):
                    items.append(self.parse_expr())
                self.expect_op(")")
                result = n.InList(left, items, negated)
            else:  # LIKE
                result = n.Binary("LIKE", left, self.parse_concat())
                if negated:
                    result = n.Not(result)
        if self._at_comparison():
            raise SQLSyntaxError("comparison operators are non-associative; use parentheses")
        return result

    def parse_concat(self) -> n.Expr:
        left = self.parse_additive()
        while self.accept_op("||"):
            left = n.Binary("||", left, self.parse_additive())
        return left

    def parse_additive(self) -> n.Expr:
        left = self.parse_multiplicative()
        while True:
            op = self.accept_op("+", "-")
            if not op:
                return left
            left = n.Binary(op, left, self.parse_multiplicative())

    def parse_multiplicative(self) -> n.Expr:
        left = self.parse_unary()
        while True:
            op = self.accept_op("*", "/", "%")
            if not op:
                return left
            left = n.Binary(op, left, self.parse_unary())

    def parse_unary(self) -> n.Expr:
        op = self.accept_op("-", "+")
        if op:
            return n.Unary(op, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> n.Expr:
        tok = self.tok
        if tok.kind in (INTEGER, REAL, STRING):
            self.advance()
            return n.Literal(tok.value)
        if tok.is_keyword("TRUE", "FALSE", "NULL"):
            self.advance()
            return n.Literal({"TRUE": True, "FALSE": False, "NULL": None}[tok.value])
        if tok.is_op("("):
            self.advance()
            if self.tok.is_keyword("SELECT"):
                query = self.parse_query()
                self.expect_op(")")
                return n.Subquery(query)
            expr = self.parse_expr()
            self.expect_op(")")
            return expr
        if tok.is_keyword("EXISTS"):
            self.advance()
            self.expect_op("(")
            if not self.tok.is_keyword("SELECT"):
                raise self.error("SELECT after EXISTS (")
            query = self.parse_query()
            self.expect_op(")")
            return n.Exists(query)
        if tok.is_keyword("CASE"):
            return self.parse_case()
        if tok.is_keyword("CAST"):
            self.advance()
            self.expect_op("(")
            operand = self.parse_expr()
            self.expect_keyword("AS")
            type_name = self.parse_type_name()
            self.expect_op(")")
            return n.Cast(operand, type_name)
        if tok.kind == IDENT:
            self.advance()
            if self.accept_op("("):
                return self.parse_call(tok.value)
            if self.accept_op("."):
                return n.ColumnRef(tok.value, self.expect_ident("column name"))
            return n.ColumnRef(None, tok.value)
        if tok.kind == KEYWORD:
            raise SQLSyntaxError(f"unexpected reserved word {tok.value}")
        raise self.error("an expression")

    def parse_case(self) -> n.Case:
        self.expect_keyword("CASE")
        operand = None if self.tok.is_keyword("WHEN") else self.parse_expr()
        whens = []
        while self.accept_keyword("WHEN"):
            cond = self.parse_expr()
            self.expect_keyword("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error("WHEN")
        else_ = self.parse_expr() if self.accept_keyword("ELSE") else None
        self.expect_keyword("END")
        return n.Case(operand, whens, else_)

    def parse_call(self, name: str) -> n.FuncCall:
        if self.accept_op("*"):
            self.expect_op(")")
            return n.FuncCall(name, [], star=True)
        distinct = bool(self.accept_keyword("DISTINCT"))
        args: list[n.Expr] = []
        if not self.tok.is_op(")"):
            args.append(self.parse_expr())
            while self.accept_op(","):
                args.append(self.parse_expr())
        self.expect_op(")")
        return n.FuncCall(name, args, distinct=distinct)


def _first_duplicate(names: list[str]) -> Optional[str]:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            return name
        seen.add(name)
    return None
