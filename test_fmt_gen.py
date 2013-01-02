#! /usr/bin/python

# Copyright 2012, 2013 Zachary Weinberg <zackw@panix.com>.
# Use, modification, and distribution are subject to the
# Boost Software License, Version 1.0.  See the file LICENSE
# or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

# This Python program generates a C++ program which will test cxxfmt.
# You need to compile its output, compile fmt.cc, link them together,
# and run the result.  The output of that program should be
# self-explanatory.

import math
import sys
import textwrap

def walk_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        for ss in walk_subclasses(sub):
            yield ss

class TestBlock(object):

    def __init__(self, group, name, casetype, generator):
        self.group = group
        self.name = name
        self.casetype = casetype
        self.generator = generator

    def __cmp__(self, other):
        # primary sort alpha by group
        if self.group < other.group: return -1
        if self.group > other.group: return 1

        # sort any block named 'simple' to the top within its group
        if self.name == "simple" and other.name != "simple": return -1
        if self.name != "simple" and other.name == "simple": return 1

        # otherwise, alphabetical
        if self.name < other.name: return -1
        if self.name > other.name: return 1
        return 0

    @classmethod
    def group_for_class(cls):
        casetype = getattr(cls, 'casetype', None)
        if casetype is None:
            raise TypeError("class '{}' lacks a casetype annotation"
                            .format(cls.__name__))
        if not casetype.startswith('case_'):
            casetype = 'case_' + casetype

        group = cls.__name__
        if group.startswith('test_'):
            group = group[5:]

        return [cls(group, name[2:], casetype, fn)
                for (name, fn) in vars(cls).iteritems()
                if callable(fn) and name.startswith('g_')]

    @classmethod
    def all_blocks(cls):
        blocks = []
        for sub in walk_subclasses(cls):
            blocks.extend(sub.group_for_class())
        blocks.sort()
        return blocks

    def emit(self, pattern, outf=None):
        txt = pattern.format(**vars(self))
        if outf is not None:
            outf.write(txt)
        return txt

    def fullname(self):
        return self.emit("{group}.{name}")

    def write_cases(self, outf):
        comment = ", ".join(str(s) for s in self.basecases())
        outf.write(textwrap.fill(comment,
                                 initial_indent="// ",
                                 subsequent_indent="// ") + "\n")
        self.emit("const {casetype} {group}_{name}[] = {{\n", outf)
        count = 0
        for case in self.generator(self):
            outf.write("  { " + case + " },\n")
            count += 1
        outf.write("}};\n// {} cases\n\n".format(count))

    def write_tblock_obj(self, outf):
        self.emit("const tblock<{casetype}> "
                  "{group}_{name}_b(\"{group}.{name}\", "
                  "{group}_{name});\n", outf)

    def write_tblocks_entry(self, outf):
        self.emit("  &{group}_{name}_b,\n", outf)

class test_string(TestBlock):
    casetype = '1arg_s'

    words = [ '', 'i', 'of', 'sis', 'fice', 'drisk', 'elanet', 'hippian',
              'botanist', 'synaptene', 'cipherhood', 'schizognath' ]

    aligns = [ '', '<', '>', '^', 'L<', 'R>', 'C^' ]

    @staticmethod
    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", "{}"'.format(spec, spec.format(val), val)

    @classmethod
    def basecases(cls):
        return ["'{}'".format(w) for w in cls.words]

    def g_simple(self):
        maxw = len(self.words) + 3

        for r in self.words:
            for a in self.aligns:
                yield self.output(a, r)

                for w in xrange(1, maxw, 3):
                    yield self.output('{}{}'.format(a, w), r)

                for p in xrange(0, maxw, 3):
                    yield self.output('{}.{}'.format(a, p), r)

                for w in xrange(1, maxw, 3):
                    for p in xrange(0, maxw, 3):
                        yield self.output('{}{}.{}'.format(a, w, p), r)

# Helpers for the next several classes.  We want to test only a few
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
        numbers = [ 0.0, 1.0, 2.0, 0.5, 4.0, 0.25, 8.0, 0.125,
                    2**19, 2**20,   # bracket {:g} switch to exponential
                    2**-13, 2**-14, # same
                  ]
        numbers.extend([i+1 for i in numbers])
        numbers.extend([-i for i in numbers])

        return sorted(set(numbers),
                      key=lambda x: (abs(math.frexp(x)[1]),
                                     abs(x),
                                     0 if x>=0 else 1))


class test_sint(TestBlock):
    casetype = '1arg_i'

    @staticmethod
    def basecases():
        return integer_test_cases(2**32, True)

    @staticmethod
    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", {}'.format(spec, spec.format(val), val)

    def g_simple(self):
        aligns = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
        types  = [ '', 'd', 'o', 'x', 'X' ]
        signs  = [ '', '+', '-', ' ' ]
        mods   = [ '', '0', '#', '#0' ]
        widths = [ '', '6', '12' ]

        for n in self.basecases():
            for a in aligns:
                for s in signs:
                    for m in mods:
                        for w in widths:
                            for t in types:
                                # Python allows these combinations,
                                # fmt.cc doesn't.
                                if '0' in m and a != '':
                                    continue
                                yield self.output(a+s+m+w+t, n)

class test_uint(TestBlock):
    casetype = '1arg_ui'

    @staticmethod
    def basecases():
        return integer_test_cases(2**32, False)

    @staticmethod
    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", {}'.format(spec, spec.format(val), val)

    def g_simple(self):
        aligns = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
        types  = [ '', 'd', 'o', 'x', 'X' ]
        signs  = [ '', '+', '-', ' ' ]
        mods   = [ '', '0', '#', '#0' ]
        widths = [ '', '6', '12' ]

        for n in self.basecases():
            for a in aligns:
                for s in signs:
                    for m in mods:
                        for w in widths:
                            for t in types:
                                # Python allows these combinations,
                                # fmt.cc doesn't.
                                if '0' in m and a != '':
                                    continue
                                yield self.output(a+s+m+w+t, n)

class test_float(TestBlock):
    casetype = '1arg_f'

    @staticmethod
    def basecases():
        return ['{:g}'.format(x) for x in float_test_cases()]

    @staticmethod
    def output(val, spec, override_spec=None):
        spec = '{:' + spec + '}'
        if override_spec is None:
            override_spec = spec
        else:
            override_spec = '{:' + override_spec + '}'

        return '"{}", "{}", {}'.format(spec, override_spec.format(val), val)

    def g_simple(self):
        aligns = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
        types  = [ '', 'e', 'f', 'g', 'E', 'F', 'G' ]
        signs  = [ '', '+', '-', ' ' ]
        mods   = [ '', '0' ]
        wnp    = [ '', '6', '12', '.6', '12.6' ]

        for n in float_test_cases():
            for a in aligns:
                for s in signs:
                    for m in mods:
                        for w in wnp:
                            for t in types:
                                if '0' in m and a != '':
                                    # Python allows these combinations,
                                    # fmt.cc doesn't.
                                    continue
                                if t == '':
                                    # Python's no-typecode behavior
                                    # for floats is not exactly any of
                                    # 'e', 'f', or 'g', and fmt.cc
                                    # doesn't mimic it.
                                    yield self.output(n, a+s+m+w, a+s+m+w+'g')
                                else:
                                    yield self.output(n, a+s+m+w+t)

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

struct case_1arg_i
{
  const char *spec;
  const char *expected;
  int val;
};

struct case_1arg_ui
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
        blocks = TestBlock.all_blocks()

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
