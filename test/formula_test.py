import unittest
from mock import Mock
from pyxlsb.formula import Formula
from pyxlsb.formula import FormulaError, FormulaParseError, FormulaLimitError
from pyxlsb.ptgs import *

class FormulaTestCase(unittest.TestCase):
    def setUp(self):
        self.wb = Mock(sheets=['Sheet1', 'Sheet2'])

    def test_stringify(self):
        self.assertEqual(Formula([StringPtg('Hello "World"')]).stringify(self.wb), '"Hello ""World"""')
        self.assertEqual(Formula([IntegerPtg(1), IntegerPtg(2), AddPtg()]).stringify(self.wb), '1+2')
        self.assertEqual(Formula([Ref3dPtg(1, 2, 3, False, False, Ref3dPtg.ptg)]).stringify(self.wb), 'Sheet2!R3C4')

    def test_stringify_nested(self):
        # The iterative renderer must produce exactly the same text as the
        # former recursive implementation, including grouping and functions.
        tokens = [
            IntegerPtg(1), IntegerPtg(2), AddPtg(), IntegerPtg(3), MultiplyPtg(),
            ParenPtg(), AttrPtg(0x40, 4), IntegerPtg(4), IntegerPtg(5),
            FuncVarPtg(9, 2, False, False, FuncVarPtg.ptg), ConcatPtg()
        ]
        self.assertEqual(Formula(tokens).stringify(self.wb), '(1+2*3)&VAR_FUNC_9(5, 4)')

    def test_attr_space_rendering(self):
        self.assertEqual(Formula([IntegerPtg(5), AttrPtg(0x40, 6)]).stringify(self.wb), '   5')
        self.assertEqual(Formula([IntegerPtg(5), AttrPtg(0x41, 0x0101)]).stringify(self.wb), '\n' * 128 + '5')

    def test_empty_formula(self):
        with self.assertRaises(FormulaParseError):
            Formula([]).stringify(self.wb)

    def test_missing_operands(self):
        with self.assertRaises(FormulaParseError):
            Formula([AddPtg()]).stringify(self.wb)
        with self.assertRaises(FormulaParseError):
            Formula([IntegerPtg(1), AddPtg()]).stringify(self.wb)
        with self.assertRaises(FormulaParseError):
            Formula([AttrPtg(0x40, 4)]).stringify(self.wb)

    def test_unbalanced_leftover_tokens(self):
        with self.assertRaises(FormulaParseError):
            Formula([IntegerPtg(1), IntegerPtg(2)]).stringify(self.wb)
        with self.assertRaises(FormulaParseError):
            Formula([IntegerPtg(1), PercentPtg(), IntegerPtg(2)]).stringify(self.wb)

    def test_funcvar_argc_exceeds_operands(self):
        with self.assertRaises(FormulaParseError):
            Formula([IntegerPtg(1), IntegerPtg(2),
                     FuncVarPtg(3, 5, False, False, FuncVarPtg.ptg)]).stringify(self.wb)

    def test_depth_limit(self):
        # A long unary chain stays tiny in tokens and output bytes but nests
        # deeply; it must be rejected without raising RecursionError.
        tokens = [IntegerPtg(0)] + [UMinusPtg() for _ in range(Formula.MAX_DEPTH)]
        with self.assertRaises(FormulaLimitError) as ctx:
            Formula(tokens).stringify(self.wb)
        self.assertEqual(ctx.exception.limit, 'depth')

    def test_depth_boundary_is_allowed(self):
        tokens = [IntegerPtg(0)] + [UMinusPtg() for _ in range(Formula.MAX_DEPTH - 1)]
        self.assertEqual(Formula(tokens).stringify(self.wb), '-' * (Formula.MAX_DEPTH - 1) + '0')

    def test_token_limit(self):
        tokens = [IntegerPtg(0)] + [PercentPtg() for _ in range(Formula.MAX_TOKENS)]
        with self.assertRaises(FormulaLimitError) as ctx:
            Formula(tokens).stringify(self.wb)
        self.assertEqual(ctx.exception.limit, 'tokens')

    def test_output_limit_blocks_attr_amplification(self):
        # Each AttrPtg can request up to ~16k spaces/newlines; several of them
        # stacked together must not be allowed to exhaust memory.
        tokens = [IntegerPtg(0)] + [AttrPtg(0x40, 0x7F00) for _ in range(5)]
        with self.assertRaises(FormulaLimitError) as ctx:
            Formula(tokens).stringify(self.wb)
        self.assertEqual(ctx.exception.limit, 'output')

    def test_output_limit_blocks_newline_amplification(self):
        tokens = [IntegerPtg(0)] + [AttrPtg(0x40, 0x7F01) for _ in range(5)]
        with self.assertRaises(FormulaLimitError) as ctx:
            Formula(tokens).stringify(self.wb)
        self.assertEqual(ctx.exception.limit, 'output')

    def test_output_limit_blocks_huge_leaf(self):
        with self.assertRaises(FormulaLimitError) as ctx:
            Formula([StringPtg('A' * (Formula.MAX_OUTPUT_BYTES + 1))]).stringify(self.wb)
        self.assertEqual(ctx.exception.limit, 'output')

    def test_error_hierarchy_is_distinguishable(self):
        self.assertTrue(issubclass(FormulaParseError, FormulaError))
        self.assertTrue(issubclass(FormulaLimitError, FormulaError))

    def test_custom_limits(self):
        class SmallOutputFormula(Formula):
            MAX_OUTPUT_BYTES = 4

        with self.assertRaises(FormulaLimitError) as ctx:
            SmallOutputFormula([IntegerPtg(1), IntegerPtg(2), AddPtg()]).stringify(self.wb)
        self.assertEqual(ctx.exception.limit, 'output')

    def test_parse_still_works(self):
        self.assertEqual(Formula.parse(b'\x1e\x2a\x00').stringify(self.wb), '42')
