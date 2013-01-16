#! /usr/bin/python

# Copyright 2012, 2013 Zachary Weinberg <zackw@panix.com>.
# Use, modification, and distribution are subject to the
# Boost Software License, Version 1.0.  See the file LICENSE
# or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

# This Python program generates a C++ program which will test cxxfmt.
# You need to compile its output, compile fmt.cc, link them together,
# and run the result.  The output of that program should be
# self-explanatory.

import curses.ascii
import itertools
import json
import math
import re
import sys
import textwrap

def redent(text, indent):
    """Remove all common indentation from 'text' and then insert
       'indent' at the beginning of each line. 'indent' can be either
       a string, which is inserted as is, or a number, which is how
       many spaces to insert."""
    if isinstance(indent, int) or isinstance(indent, long):
        indent = ' '*indent
    return '\n'.join(indent+l for l in textwrap.dedent(text).split('\n'))

_tosymbol_re = re.compile(r"[^A-Za-z0-9_]+")
def tosymbol(name):
    """Make 'name' into a valid C++ symbol."""
    name = _tosymbol_re.sub("_", name)
    if name[0] in "0123456789_":
        name = "N"+name
    return name

class TestCaseType(object):
    """POD structure containing all information required for one subtest."""
    allcasetypes = {}

    def __init__(self, vtypes, caseprinter):
        self.vtypes = vtypes
        self.caseprinter = caseprinter
        self.name = caseprinter.__name__

        if self.name in self.allcasetypes:
            raise RuntimeError("duplicate casetype name: " + self.name)
        self.allcasetypes[self.name] = self

    def __cmp__(self, other):
        return cmp(self.name, other.name)

    def write_case(self, outf, args):
        try:
            outf.write("  { " + self.caseprinter(*args) + " },\n")
        except:
            sys.stderr.write("\n*** args: " + repr(args) + "\n")
            raise

    def write_decl(self, outf):
        outf.write("struct {}\n".format(self.name))
        outf.write("{\n  const char* spec;\n  const char* expected;\n")
        for i_t in enumerate(self.vtypes):
            outf.write("  {1} v{0};\n".format(*i_t))
        outf.write("};\n\n")

class caseprint(object):
    """Decorator to facilitate creation of TestCaseTypes from
       case printer functions."""
    def __init__(self, vtypes):
        if not isinstance(vtypes, tuple):
            self.vtypes = (vtypes,)
        else:
            self.vtypes = vtypes
    def __call__(self, fn):
        return TestCaseType(self.vtypes, fn)

# Python string literals can be set off with single quotes, and repr()
# prefers that form, so it usually doesn't produce a valid C string
# literal.  But the JSON string literal syntax is the same as the C
# string literal syntax, so we can use json.dumps() instead.

@caseprint( () )
def case_a0(spec, output):
    # The spec may contain deliberate syntax errors marked with angle
    # brackets.  They are removed from 'spec', and replaced with VT220
    # escape sequences in 'output'.
    spec = json.dumps(spec.replace('<', '').replace('>', ''))
    # json produces \u001b for ESC, which would theoretically work in
    # C++11, but I feel safer sticking to good old \x1b.
    output = json.dumps(output.replace('<', '\x1b[7m')
                              .replace('>', '\x1b[27m')).replace('\\u001b',
                                                                 '\\x1b')
    return spec + ", " + output

def case_a1(spec, override_spec, val, cval):
    spec = '{:' + spec + '}'
    override_spec = '{:' + override_spec + '}'
    formatted = override_spec.format(val)
    return json.dumps(spec) + ", " + json.dumps(formatted) + ", " + cval

@caseprint('const char*')
def case_a1_cs(val, spec):
    return case_a1(spec, spec, val, json.dumps(val))

@caseprint('int')
def case_a1_is(val, spec):
    return case_a1(spec, spec, val, str(val))

@caseprint('unsigned int')
def case_a1_iu(val, spec):
    return case_a1(spec, spec, val, str(val))

@caseprint('long long')
def case_a1_lls(val, spec):
    # Special case -(2**63), which may trigger "integer constant is so
    # large that it is unsigned" warnings even when properly suffixed.
    if val == -2**63:
        sval = "{}LL - 1LL".format(val+1)
    else:
        sval = str(val) + "LL"
    return case_a1(spec, spec, val, sval)

@caseprint('unsigned long long')
def case_a1_llu(val, spec):
    return case_a1(spec, spec, val, str(val)+"LLU")

@caseprint('float')
def case_a1_f(val, spec):
    ospec = spec
    # Python's no-typecode behavior for floats is not exactly
    # any of 'e', 'f', or 'g'.  fmt.cc treats it the same as 'g'.
    if len(spec) == 0 or spec[-1] not in "eEfFgG":
        ospec += 'g'
    return case_a1(spec, ospec, val, str(val))

@caseprint('char')
def case_a1_c(val, spec):
    # Python has no stock way to print a valid C character literal.
    if len(val) > 1:
        raise ValueError("{!r} is not a one-character string".format(val))
    if curses.ascii.isprint(val) and val != "'":
        cval = "'" + val + "'"
    else:
        cval = "'\\x{:02x}'".format(ord(val))
    # Python doesn't support printing characters with numeric
    # typecodes (which fmt.cc does). 'c' counts as a numeric
    # typecode.
    if len(spec) > 0 and spec[-1] in "cdoxX":
        val = ord(val)
    ospec = spec
    return case_a1(spec, ospec, val, cval)

class TestBlock(object):
    """One block of tests.  All tests in a block share the same
       'casetype'."""
    allblocks = {}

    def __init__(self, casetype, generator, name = None):
        self.casetype = casetype
        self.generator = generator
        if name is None:
            self.name = generator.__name__
            if self.name.startswith('test_'):
                self.name = self.name[5:]
        else:
            self.name = name
        self.symbol = tosymbol(self.name)

        if self.name in self.allblocks:
            raise RuntimeError("duplicate test block name: " + self.name)
        self.allblocks[self.name] = self

    def __cmp__(self, other):
        # We want all tests that use the same casetype to be grouped together.
        return (cmp(self.casetype, other.casetype) or
                cmp(self.name, other.name))

    def write_cases(self, outf):
        outf.write("const {0} tc_{1}[] = {{\n"
                   .format(self.casetype.name, self.symbol))
        count = 0
        for case in self.generator():
            self.casetype.write_case(outf, case)
            count += 1
        outf.write("}};\n// {} cases\n\n".format(count))

    def write_process_fn(self, outf):
        pass

    def write_process_call(self, outf):
        outf.write('  success &= process("{0}", tc_{1});\n'
                   .format(self.name, self.symbol))

class VarTB(TestBlock):
    """A block of tests which reuses an existing block with a different
       'process1' function."""

    process_template = textwrap.dedent("""\
          static bool
          process1_{0}(const {1}& c)
          {{
          {2}
            return process1_T(c.spec, c.expected, {3});
          }}

          """)

    def __init__(self, depblock, p1name, p1body):
        self.depblock = depblock
        self.p1name = p1name
        self.p1sym  = tosymbol(p1name)
        self.p1body = redent(p1body, 2)

        TestBlock.__init__(self, depblock.casetype, lambda: [],
                           depblock.name + " (" + p1name + ")")

    def write_cases(self, outf):
        pass

    def write_process_fn(self, outf):
        vs = ", ".join("v"+str(i) for i in range(len(self.casetype.vtypes)))
        outf.write(self.process_template.format(self.p1sym,
                                                self.casetype.name,
                                                self.p1body, vs))

    def write_process_call(self, outf):
        outf.write('  success &= process("{0}", tc_{1}, process1_{2});\n'
                   .format(self.name, self.depblock.symbol, self.p1sym))

class testgen(object):
    """Decorator to facilitate creation of TestBlocks from test
       generator functions."""
    def __init__(self, casetype, name):
        self.casetype = casetype
        self.name = name
    def __call__(self, fn):
        return TestBlock(self.casetype, fn, self.name)

@testgen(case_a0, "format-spec syntax errors")
def test_syntax_errors():
    return (x if isinstance(x, tuple) else (x,x) for x in [
        "no error",
        ( "no error {{", "no error {" ),
        ( "no error }}", "no error }" ),
        ( "no error }}{{{{}}", "no error }{{}" ),
        ( "absent argument <{}>", "absent argument <[missing]>" ),
        ( "absent argument <{:}>", "absent argument <[missing]>" ),
        "unbalanced <{>",
        "unbalanced <}>",
        ( "unbalanced {{<{>", "unbalanced {<{>" ),
        ( "unbalanced }}<}>", "unbalanced }<}>" ),
        "unbalanced <{0>",
        "unbalanced <{:>",
        "unbalanced <{:=>",
        "unbalanced <{:E=>",
        "unbalanced <{:0.0>",
        "misordered <{:0+}>",
        "misordered <{:0-}>",
        "misordered <{:0 }>",
        "misordered <{:0#}>",
        "misordered <{:#+}>",
        "misordered <{:#-}>",
        "misordered <{:# }>",
        "not a number <{:Z}>",
        "not a number <{:.Z}>",
        "not a number <{:Z.Z}>",
        "trailing junk <{:0.0Z}>",
        "zerofill with alignment <{:=0}>",
        "zerofill with alignment <{:0=0}>",
        "not yet supported <{0:{1}}>",
        "not yet supported <{0:.{1}}>",
        "not yet supported <{0:{1}.{2}}>",
        "not yet supported <{:b}>",
        "not yet supported <{:n}>",
        "not yet supported <{:%}>",
        "no plan to support <{expr}>",
        "no plan to support <{.expr}>",
        "no plan to support <{0.expr}>",
        "no plan to support <{!r}>",
        "no plan to support <{!s}>",
        "no plan to support <{!b}>",
        "no plan to support <{0!r}>",
        "no plan to support <{0!s}>",
        "no plan to support <{0!b}>",
        ])

@testgen(case_a1_cs, "formatting strings")
def test_str():

    words = [ '', 'i', 'of', 'sis', 'fice', 'drisk', 'elanet', 'hippian',
              'botanist', 'synaptene', 'cipherhood', 'schizognath' ]

    aligns = [ '', '<', '>', '^', 'L<', 'R>', 'C^' ]

    maxw = len(words) + 3

    for r in words:
        for a in aligns:
            yield (r, a)
            yield (r, a+'s')

            for w in xrange(1, maxw, 3):
                yield (r, '{}{}'.format(a, w))

            for p in xrange(0, maxw, 3):
                yield (r, '{}.{}'.format(a, p))

            for w in xrange(1, maxw, 3):
                for p in xrange(0, maxw, 3):
                    yield (r, '{}{}.{}'.format(a, w, p))

test_str_stdstr = VarTB(test_str, "std::string",
                        "string v0(c.v0);")
test_str_stdexc = VarTB(test_str, "std::exception",
                        "logic_error v0(c.v0);")
test_str_csconv = VarTB(test_str, "conversion to char*", """\
                          struct ts {
                            const char* s;
                            ts(const char* s_) : s(s_) {}
                            operator const char* () const { return s; }
                          };
                          ts v0(c.v0);""")
test_str_csstr  = VarTB(test_str, "str() method (char *)", """\
                          struct ts {
                            const char* s;
                            ts(const char *s_) : s(s_) {}
                            const char* str() const { return s; }
                          };
                          ts v0(c.v0);""")
test_str_cscstr = VarTB(test_str, "c_str() method", """\
                          struct ts {
                            const char *s;
                            ts(const char *s_) : s(s_) {}
                            const char* c_str() const { return s; }
                          };
                          ts v0(c.v0);""")
test_str_ssconv = VarTB(test_str, "conversion to std::string", """\
                          struct ts {
                            const char *s;
                            ts(const char *s_) : s(s_) {}
                            operator string() const { return string(s); }
                          };
                          ts v0(c.v0);""")
test_str_ssstr  = VarTB(test_str, "str() method (std::string)", """\
                          struct ts {
                            const char *s;
                            ts(const char *s_) : s(s_) {}
                            string str() const { return string(s); }
                          };
                          ts v0(c.v0);""")

@testgen(case_a1_c, "formatting chars")
def test_char():
    chars  = "a!'0\t"
    types  = [ '', 'c', 's', 'd', 'o', 'x', 'X' ]
    aligns = [ '', '<', '>', '^', 'L<', 'R>', 'C^' ]
    widths = [ '', '1', '3', '4' ]
    precs  = [ '', '.0', '.1', '.3', '.4' ]

    for (r, t, a, w, p) in itertools.product(chars, types, aligns,
                                             widths, precs):
        if (t != '' and t != 's') and p != '':
            continue # integer formatting doesn't allow precision
        yield (r, a+w+p+t)

test_char_uchar = VarTB(test_char, "unsigned", "unsigned char v0 = c.v0;")
test_char_schar = VarTB(test_char, "signed", "signed char v0 = c.v0;")

# Helpers for the next several tests.  We want to test only a few
# numbers, because there are so many modifier combinations to work
# through for each (~2000 for integers, ~2500 for floats) so we could
# easily end up with hundreds of thousands of subtests if we didn't
# watch it, and then the generated test program would take ages to
# compile.  But we want to make sure we hit lots of "interesting"
# numeric thresholds.  For floating point, we also need to make sure
# that tests do not depend on Python's very sophisticated
# floating-point-to-decimal conversion algorithm, which guarantees to
# print the shortest decimal number that rounds to the IEEE double it
# began with (as modified by the format spec); your C++ library probably
# does not make the same guarantee.

def integer_test_cases(limit, any_negative):
    numbers = [ 1, 128, 256, 32768, 65536, 2**31, 2**32, 2**63, 2**64 ]
    # The square brackets on the next line prevent an infinite loop.
    numbers.extend([i-1 for i in numbers])

    if any_negative:
        numbers.extend([-i for i in numbers])
        numbers = [i for i in numbers if -(limit/2) <= i <= limit/2 - 1]
    else:
        numbers = [i for i in numbers if i <= limit - 1]

    # remove duplicates and sort into order 0, 1, -1, ...
    numbers = sorted(set(numbers),
                     key=lambda x: (abs(x), 0 if x>=0 else 1))
    return numbers

def float_test_cases():
        numbers = [ 0.0, 1.0, 2.0, 0.5,
                    2**19, 2**20,   # bracket {:g} switch to exponential
                    2**-13, 2**-14, # same
                  ]
        numbers.extend([i+1 for i in numbers])
        numbers.extend([-i for i in numbers])

        return sorted(set(numbers),
                      key=lambda x: (abs(math.frexp(x)[1]),
                                     abs(x),
                                     0 if x>=0 else 1))

@testgen(case_a1_is, "formatting signed ints")
def test_int_signed():

    numbers = integer_test_cases(2**32, True)
    aligns  = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
    types   = [ '', 'd', 'o', 'x', 'X', 'g' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0', '#', '#0' ]
    widths  = [ '', '6', '12' ]

    for (n,a,s,m,w,t) in itertools.product(numbers, aligns, signs,
                                           mods, widths, types):
        # Skip '0' modifier with explicit alignment.
        # Python allows this combination, fmt.cc doesn't.
        # Also skip '#' with 'g', which is not allowed by either.
        if ((a == '' or '0' not in m) and
            (t != 'g' or '#' not in m)):
            yield (n, a+s+m+w+t)

@testgen(case_a1_iu, "formatting unsigned ints")
def test_int_unsigned():

    numbers = integer_test_cases(2**32, False)
    aligns  = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
    types   = [ '', 'd', 'o', 'x', 'X', 'g' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0', '#', '#0' ]
    widths  = [ '', '6', '12' ]

    for (n,a,s,m,w,t) in itertools.product(numbers, aligns, signs,
                                           mods, widths, types):
        # Skip '0' modifier with explicit alignment.
        # Python allows this combination, fmt.cc doesn't.
        # Also skip '#' with 'g', which is not allowed by either.
        if ((a == '' or '0' not in m) and
            (t != 'g' or '#' not in m)):
            yield (n, a+s+m+w+t)

# Test very large numbers with a reduced set of format modifiers.
@testgen(case_a1_lls, "formatting signed long longs")
def test_long_signed():
    numbers = integer_test_cases(2**64, True)
    types   = [ '', 'd', 'o', 'x', 'X' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0', '#', '#0' ]
    for (n,t,s,m) in itertools.product(numbers, types, signs, mods):
        yield (n, s+m+t)

@testgen(case_a1_llu, "formatting unsigned long longs")
def test_long_unsigned():
    numbers = integer_test_cases(2**64, False)
    types   = [ '', 'd', 'o', 'x', 'X' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0', '#', '#0' ]
    for (n,t,s,m) in itertools.product(numbers, types, signs, mods):
        yield (n, s+m+t)

@testgen(case_a1_f, "formatting floats")
def test_float():

    numbers = float_test_cases()
    aligns  = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
    types   = [ '', 'e', 'f', 'g', 'E', 'F', 'G' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0' ]
    wnp     = [ '', '6', '12', '.6', '12.6' ]

    for (n,a,s,m,w,t) in itertools.product(numbers, aligns, signs,
                                           mods, wnp, types):
        # Skip '0' modifier with explicit alignment.
        # Python allows this combination, fmt.cc doesn't.
        if a == '' or '0' not in m:
            yield (n, a+s+m+w+t)

# We don't attempt to test values not representable in single
# precision, for fear of hitting variance between floating-point
# conversion libraries.
test_float_dbl = VarTB(test_float, "double", "double v0 = c.v0;")

skeleton_0 = r"""// Tester for cxxfmt.

// Copyright 2012 Zachary Weinberg <zackw@panix.com>.
// Use, modification, and distribution are subject to the
// Boost Software License, Version 1.0.  See the file LICENSE
// or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

// This program was generated by test_fmt.py.  DO NOT EDIT.
// Edit test_fmt.py instead.

#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <fmt.h>

using std::cout;
using std::logic_error;
using std::flush;
using std::strcmp;
using std::string;
using fmt::format;

namespace {

bool quiet = false;

// Note: Plain arrays of POD structures are used because some
// compilers are not yet very good at optimizing std::initializer_list,
// leading to gargantuan assembly output and very slow object file
// generation.

"""

skeleton_1 = r"""static bool
report(const char* spec, string const& got, const char* expected)
{
  if (got == expected)
    return true;
  else {
    if (!quiet)
      cout << "\nFAIL: " << spec
           << ": want '" << expected
           << "', got '" << got
           << '\'';
    return false;
  }
}

#define MAKE_HAS_TRAIT(memb)                                    \
  template <typename T>                                         \
  class has_##memb                                              \
  {                                                             \
    struct one { char x[1]; };                                  \
    struct two { char x[2]; };                                  \
    template <typename C> static one test(decltype(&C::memb));  \
    template <typename C> static two test(...);                 \
  public:                                                       \
    enum { value = sizeof(test<T>(0)) == sizeof(char) };        \
  } /* deliberate absence of semicolon */

MAKE_HAS_TRAIT(v0);
MAKE_HAS_TRAIT(v1);

template <typename T>
static bool
process1_T(const char *spec, const char *expected, T const& val)
{
  string got(format(spec, val));
  return report(spec, got, expected);
}

template <typename case_a0,
          typename = typename std::enable_if<!has_v0<case_a0>::value>::type>
static bool
process1_generic(const case_a0& c)
{
  string got(format(c.spec));
  return report(c.spec, got, c.expected);
}

template <typename case_a1,
          typename = typename std::enable_if<has_v0<case_a1>::value>::type,
          typename = typename std::enable_if<!has_v1<case_a1>::value>::type>
static bool
process1_generic(const case_a1& c)
{
  return process1_T(c.spec, c.expected, c.v0);
}

"""

skeleton_2 = r"""
template <typename caseT, size_t n>
static bool
process(const char *tag, const caseT (&cases)[n],
        bool (*process1)(const caseT&) = process1_generic<caseT>)
{
  if (!quiet)
    cout << "test " << tag << "..." << flush;
  bool success = true;
  for (const caseT* c = cases; c < cases+n; c++)
    success &= process1(*c);
  if (!quiet) {
    if (success)
      cout << " ok\n";
    else
      cout << '\n'; // failures printed already
  }
  return success;
}

} // anonymous namespace

int
main(int argc, char** argv)
{
  if (argc > 1 && !strcmp(argv[1], "-q"))
    quiet = true;
  bool success = true;

"""

skeleton_3 = r"""
  return success ? 0 : 1;
}
"""

def main():
    if len(sys.argv) > 1:
        outf = open(sys.argv[1], "w")
    else:
        outf = sys.stdout

    with outf:
        outf.write(skeleton_0)

        casets = TestCaseType.allcasetypes.values()
        casets.sort()
        for ct in casets: ct.write_decl(outf)

        blocks = TestBlock.allblocks.values()
        blocks.sort()
        for b in blocks: b.write_cases(outf)

        outf.write(skeleton_1)

        for b in blocks: b.write_process_fn(outf)

        outf.write(skeleton_2)

        for b in blocks: b.write_process_call(outf)

        outf.write(skeleton_3)

assert __name__ == '__main__'
main()
