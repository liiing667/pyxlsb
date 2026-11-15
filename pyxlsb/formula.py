from .tokenreader import TokenReader
from . import ptgs


class FormulaError(Exception):
    """Base class for every error raised while rendering a formula."""


class FormulaParseError(FormulaError):
    """Raised when a formula token stream is malformed.

    Typical causes are an empty token stream, an operator without enough
    operands on the PTG stack, or leftover tokens that never get consumed.
    """


class FormulaLimitError(FormulaError):
    """Raised when a formula exceeds one of the rendering budgets.

    The ``limit`` attribute identifies the budget that was exceeded:
    ``'tokens'``, ``'depth'`` or ``'output'``.
    """

    def __init__(self, limit, message):
        super(FormulaLimitError, self).__init__(message)
        self.limit = limit


class _RenderedOperand(object):
    """A PTG stand-in holding the already rendered text of an operand."""

    def __init__(self, text):
        self._text = text

    def stringify(self, tokens, workbook):
        return self._text


def _arity(token):
    """Number of operands a token pops off the PTG stack when rendered."""
    if isinstance(token, ptgs.FuncVarPtg):
        return token.argc
    if isinstance(token, (ptgs.UPlusPtg, ptgs.UMinusPtg, ptgs.PercentPtg,
                          ptgs.ParenPtg, ptgs.AttrPtg)):
        return 1
    if isinstance(token, (ptgs.AddPtg, ptgs.SubstractPtg, ptgs.MultiplyPtg,
                          ptgs.DividePtg, ptgs.PowerPtg, ptgs.ConcatPtg,
                          ptgs.LessPtg, ptgs.LessEqualPtg, ptgs.EqualPtg,
                          ptgs.GreaterEqualPtg, ptgs.GreaterPtg,
                          ptgs.NotEqualPtg, ptgs.IntersectionPtg,
                          ptgs.UnionPtg, ptgs.RangePtg)):
        return 2
    return 0


class Formula(object):
    # A single formula is bounded well below the Excel/parser limits so that a
    # malicious token stream cannot exhaust the host's memory or stack.
    MAX_TOKENS = 4096
    MAX_DEPTH = 128
    MAX_OUTPUT_BYTES = 65536

    def __init__(self, tokens):
        self._tokens = list(tokens)

    def __repr__(self):
        return 'Formula({})'.format(self._tokens)

    def __str__(self):
        return self.stringify()

    def stringify(self, workbook):
        tokens = self._tokens

        if not tokens:
            raise FormulaParseError('cannot stringify an empty formula')
        if len(tokens) > self.MAX_TOKENS:
            raise FormulaLimitError(
                'tokens',
                'formula has {} tokens, limit is {}'.format(len(tokens), self.MAX_TOKENS)
            )

        # First pass: validate the postfix token stream. Every operator must
        # find enough operands on the stack, exactly one value must remain at
        # the end and the expression depth must stay within the budget. A
        # separate depth stack tracks the AST depth of every stacked value so
        # long unary chains are bounded even though they never grow the stack.
        stack_size = 0
        depth_stack = []
        for token in tokens:
            arity = _arity(token)
            if arity > stack_size:
                raise FormulaParseError(
                    'not enough operands for {}'.format(type(token).__name__)
                )
            stack_size -= arity
            stack_size += 1
            if arity:
                child_depths = depth_stack[-arity:]
                del depth_stack[-arity:]
                depth = max(child_depths) + 1
            else:
                depth = 1
            depth_stack.append(depth)
            if depth > self.MAX_DEPTH:
                raise FormulaLimitError(
                    'depth',
                    'formula nesting exceeds depth limit of {}'.format(self.MAX_DEPTH)
                )

        if stack_size != 1:
            raise FormulaParseError(
                'unbalanced formula: {} values left on the stack'.format(stack_size)
            )

        # Second pass: render iteratively so a deep (but otherwise valid)
        # formula cannot trigger a RecursionError. Rendered operands are pushed
        # back as leaf tokens, letting every PTG keep its own stringify logic
        # while the produced text is charged against the output budget.
        pending = list(reversed(tokens))
        operand_stack = []
        output_size = 0

        while pending:
            token = pending.pop()
            arity = _arity(token)
            if arity:
                pending.extend(operand_stack[-arity:])
                del operand_stack[-arity:]

            text = token.stringify(pending, workbook)
            output_size += len(text)
            if output_size > self.MAX_OUTPUT_BYTES:
                raise FormulaLimitError(
                    'output',
                    'formula output exceeds limit of {} bytes'.format(self.MAX_OUTPUT_BYTES)
                )
            operand_stack.append(_RenderedOperand(text))

        return operand_stack[0]._text

    @classmethod
    def parse(cls, data):
        return cls(TokenReader(data))
