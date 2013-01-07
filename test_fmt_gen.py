#! /usr/bin/python

# Copyright 2012, 2013 Zachary Weinberg <zackw@panix.com>.
# Use, modification, and distribution are subject to the
# Boost Software License, Version 1.0.  See the file LICENSE
# or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

# This Python program generates a C++ program which will test cxxfmt.
# You need to compile its output, compile fmt.cc, link them together,
# and run the result.  The output of that program should be
# self-explanatory.

import itertools
import math
import sys

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
        outf.write("  { " + self.caseprinter(*args) + " },\n")

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

def case_a1(tmpl, val, spec, override_spec):
    spec = '{:' + spec + '}'
    if override_spec is None:
        override_spec = spec
    else:
        override_spec = '{:' + override_spec + '}'
    tmpl = '"{}", "{}", ' + tmpl
    return tmpl.format(spec, override_spec.format(val), val)

@caseprint('const char*')
def case_a1_cs(val, spec, override_spec=None):
    return case_a1('"{}"', val, spec, override_spec)

@caseprint('int')
def case_a1_is(val, spec, override_spec=None):
    return case_a1('{}', val, spec, override_spec)

@caseprint('unsigned int')
def case_a1_us(val, spec, override_spec=None):
    return case_a1('{}', val, spec, override_spec)

@caseprint('double')
def case_a1_d(val, spec, override_spec=None):
    return case_a1('{}', val, spec, override_spec)

class TestBlock(object):
    """One block of tests.  All tests in a block share the same
       'casetype'."""
    allblocks = {}

    def __init__(self, casetype, generator):
        self.casetype = casetype
        self.generator = generator
        self.name = generator.__name__
        if self.name.startswith('test_'):
            self.name = self.name[5:]

        if self.name in self.allblocks:
            raise RuntimeError("duplicate test block name: " + name)
        self.allblocks[self.name] = self

    def __cmp__(self, other):
        # We want all tests that use the same casetype to be grouped together.
        return (cmp(self.casetype, other.casetype) or
                cmp(self.name, other.name))

    def write_cases(self, outf):
        outf.write("const {0} tc_{1}[] = {{\n"
                   .format(self.casetype.name, self.name))
        count = 0
        for case in self.generator():
            self.casetype.write_case(outf, case)
            count += 1
        outf.write("}};\n// {} cases\n\n".format(count))

    def write_process_call(self, outf):
        outf.write('  success &= process("{0}", tc_{0});\n'.format(self.name))

class testgen(object):
    """Decorator to facilitate creation of TestBlocks from test
       generator functions."""
    def __init__(self, casetype):
        self.casetype = casetype
    def __call__(self, fn):
        return TestBlock(self.casetype, fn)

@testgen(case_a1_cs)
def test_cstr():

    words = [ '', 'i', 'of', 'sis', 'fice', 'drisk', 'elanet', 'hippian',
              'botanist', 'synaptene', 'cipherhood', 'schizognath' ]

    aligns = [ '', '<', '>', '^', 'L<', 'R>', 'C^' ]

    maxw = len(words) + 3

    for r in words:
        for a in aligns:
            yield (r, a)

            for w in xrange(1, maxw, 3):
                yield (r, '{}{}'.format(a, w))

            for p in xrange(0, maxw, 3):
                yield (r, '{}.{}'.format(a, p))

            for w in xrange(1, maxw, 3):
                for p in xrange(0, maxw, 3):
                    yield (r, '{}{}.{}'.format(a, w, p))

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

@testgen(case_a1_is)
def test_int_signed():

    numbers = integer_test_cases(2**32, True)
    aligns  = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
    types   = [ '', 'd', 'o', 'x', 'X' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0', '#', '#0' ]
    widths  = [ '', '6', '12' ]

    for (n,a,s,m,w,t) in itertools.product(numbers, aligns, signs,
                                           mods, widths, types):
        # Skip '0' modifier with explicit alignment.
        # Python allows this combination, fmt.cc doesn't.
        if a == '' or '0' not in m:
            yield (n, a+s+m+w+t)

@testgen(case_a1_us)
def test_int_unsigned():

    numbers = integer_test_cases(2**32, False)
    aligns  = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
    types   = [ '', 'd', 'o', 'x', 'X' ]
    signs   = [ '', '+', '-', ' ' ]
    mods    = [ '', '0', '#', '#0' ]
    widths  = [ '', '6', '12' ]

    for (n,a,s,m,w,t) in itertools.product(numbers, aligns, signs,
                                           mods, widths, types):
        # Skip '0' modifier with explicit alignment.
        # Python allows this combination, fmt.cc doesn't.
        if a == '' or '0' not in m:
            yield (n, a+s+m+w+t)

@testgen(case_a1_d)
def test_double():

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
            if t == '':
                # Python's no-typecode behavior for floats is not exactly
                # any of 'e', 'f', or 'g'.  fmt.cc treats it the same as 'g'.
                yield (n, a+s+m+w, a+s+m+w+'g')
            else:
                yield (n, a+s+m+w+t)

skeleton_top = r"""// Tester for cxxfmt.

// Copyright 2012 Zachary Weinberg <zackw@panix.com>.
// Use, modification, and distribution are subject to the
// Boost Software License, Version 1.0.  See the file LICENSE
// or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

// This program was generated by test_fmt.py.  DO NOT EDIT.
// Edit test_fmt.py instead.

#include <cstring>
#include <string>
#include <iostream>
#include <fmt.h>

using std::strcmp;
using std::string;
using std::cout;
using std::flush;
using fmt::format;

namespace {

bool quiet = false;

// Note: Plain arrays of POD structures are used because some
// compilers are not yet very good at optimizing std::initializer_list,
// leading to gargantuan assembly output and very slow object file
// generation.

"""

skeleton_mid = r"""static bool
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

template <typename case_a1>
static bool
process1_generic(const case_a1& c)
{
  string got(format(c.spec, c.v0));
  return report(c.spec, got, c.expected);
}

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

skeleton_bot = """
  return success ? 0 : 1;
}
"""

def main():
    if len(sys.argv) > 1:
        outf = open(sys.argv[1], "w")
    else:
        outf = sys.stdout

    with outf:
        outf.write(skeleton_top)

        casets = TestCaseType.allcasetypes.values()
        casets.sort()
        for ct in casets: ct.write_decl(outf)

        blocks = TestBlock.allblocks.values()
        blocks.sort()
        for b in blocks: b.write_cases(outf)

        outf.write(skeleton_mid)

        for b in blocks: b.write_process_call(outf)

        outf.write(skeleton_bot)

assert __name__ == '__main__'
main()
