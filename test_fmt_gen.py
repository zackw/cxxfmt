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

class TestBlock(object):
    allblocks = []

    def __init__(self, casetype, generator):
        self.casetype = casetype
        self.generator = generator
        self.name = generator.__name__
        if self.name.startswith('test_'):
            self.name = self.name[5:]
        self.allblocks.append(self)

    def __cmp__(self, other):
        return (cmp(self.casetype, other.casetype) or
                cmp(self.name, other.name) or
                cmp(self.generator, other.generator))

    def emit(self, pattern, outf=None):
        txt = pattern.format(**vars(self))
        if outf is not None:
            outf.write(txt)
        return txt

    def write_cases(self, outf):
        self.emit("const case_{casetype} {name}_tests[] = {{\n", outf)
        count = 0
        for case in self.generator():
            outf.write("  { " + case + " },\n")
            count += 1
        outf.write("}};\n// {} cases\n\n".format(count))

    def write_tblock_obj(self, outf):
        self.emit("const tblock<case_{casetype}> "
                  "tg_{name}(\"{name}\", {name}_tests);\n", outf)

    def write_tblocks_entry(self, outf):
        self.emit("  &tg_{name},\n", outf)

class testgen(object):
    """Decorator to facilitate creation of TestBlocks from test
       generator functions."""
    def __init__(self, casetype):
        self.casetype = casetype
    def __call__(self, fn):
        return TestBlock(self.casetype, fn)

@testgen('1arg_s')
def test_cstr():

    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", "{}"'.format(spec, spec.format(val), val)

    words = [ '', 'i', 'of', 'sis', 'fice', 'drisk', 'elanet', 'hippian',
              'botanist', 'synaptene', 'cipherhood', 'schizognath' ]

    aligns = [ '', '<', '>', '^', 'L<', 'R>', 'C^' ]

    maxw = len(words) + 3

    for r in words:
        for a in aligns:
            yield output(a, r)

            for w in xrange(1, maxw, 3):
                yield output('{}{}'.format(a, w), r)

            for p in xrange(0, maxw, 3):
                yield output('{}.{}'.format(a, p), r)

            for w in xrange(1, maxw, 3):
                for p in xrange(0, maxw, 3):
                    yield output('{}{}.{}'.format(a, w, p), r)

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

@testgen('1arg_is')
def test_int_signed():

    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", {}'.format(spec, spec.format(val), val)

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
            yield output(a+s+m+w+t, n)

@testgen('1arg_iu')
def test_int_unsigned():

    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", {}'.format(spec, spec.format(val), val)

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
            yield output(a+s+m+w+t, n)

@testgen('1arg_f')
def test_float():

    def output(val, spec, override_spec=None):
        spec = '{:' + spec + '}'
        if override_spec is None:
            override_spec = spec
        else:
            override_spec = '{:' + override_spec + '}'

        return '"{}", "{}", {}'.format(spec, override_spec.format(val), val)

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
                yield output(n, a+s+m+w, a+s+m+w+'g')
            else:
                yield output(n, a+s+m+w+t)

skeleton_top = r"""// Tester for cxxfmt.

// Copyright 2012 Zachary Weinberg <zackw@panix.com>.
// Use, modification, and distribution are subject to the
// Boost Software License, Version 1.0.  See the file LICENSE
// or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

// This program was generated by test_fmt.py.  DO NOT EDIT.
// Edit test_fmt.py instead.

#ifndef COMPILER_NAME
#define COMPILER_NAME "unknown"
#endif

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

struct case_1arg_s
{
  const char *spec;
  const char *expected;
  const char *val;
};

struct case_1arg_is
{
  const char *spec;
  const char *expected;
  int val;
};

struct case_1arg_iu
{
  const char *spec;
  const char *expected;
  unsigned int val;
};

struct case_1arg_f
{
  const char *spec;
  const char *expected;
  float val;
};

// more case_ structures here

static bool
report(const char *spec, string const& got, const char *expected)
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

template <typename case_1arg>
static bool
process(const case_1arg *cases, size_t n)
{
  bool success = true;
  for (const case_1arg *c = cases; c < cases+n; c++) {
    string got(format(c->spec, c->val));
    success &= report(c->spec, got, c->expected);
  }
  return success;
}

// more process_ overloads here

struct i_tblock { virtual bool operator()(const char *) const = 0; };

template <typename case_1arg>
struct tblock : i_tblock
{
  template <size_t N>
  tblock(const char *tag_, const case_1arg (&cases_)[N])
    : tag(tag_), cases(cases_), n(N)
  {}

  virtual bool operator()(const char *label_) const
  {
    string label(label_);
    label += '\t';
    label += tag;
    if (!quiet)
      cout << label << "..." << flush;
    bool success = process(cases, n);
    if (!quiet) {
      if (success)
        cout << " ok\n";
      else
        cout << '\n'; // failures printed already
    }
    return success;
  }

private:
  const char *tag;
  const case_1arg *cases;
  size_t n;
};

"""

skeleton_bot = r"""

} // anonymous namespace

int
main(int argc, char **argv)
{
  if (argc > 1 && !strcmp(argv[1], "-q"))
    quiet = true;
  bool success = true;
  for (size_t i = 0; i < n_tblocks; i++)
    success &= (*tblocks[i])(COMPILER_NAME);
  return success ? 0 : 1;
}
"""

def main():
    if len(sys.argv) > 1:
        outf = open(sys.argv[1], "w")
    else:
        outf = sys.stdout

    with outf:
        blocks = TestBlock.allblocks

        outf.write(skeleton_top)
        for b in blocks: b.write_cases(outf)
        for b in blocks: b.write_tblock_obj(outf)

        outf.write("\nconst i_tblock *const tblocks[] = {\n")
        for b in blocks: b.write_tblocks_entry(outf)
        outf.write("};\nconst size_t n_tblocks = "
                   "sizeof(tblocks) / sizeof(tblocks[0]);")
        outf.write(skeleton_bot)

assert __name__ == '__main__'
main()
