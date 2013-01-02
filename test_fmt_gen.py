#! /usr/bin/python

# Copyright 2012 Zachary Weinberg <zackw@panix.com>.
# Use, modification, and distribution are subject to the
# Boost Software License, Version 1.0.  See the file LICENSE
# or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

# This Python program generates a C++ program which will test cxxfmt.
# You need to compile its output, compile fmt.cc, link them together,
# and run the result.  The output of that program should be
# self-explanatory.

import sys

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
        self.emit("const {casetype} {group}_{name}[] = {{\n", outf)
        for case in self.generator(self):
            outf.write("  { " + case + " },\n")
        outf.write("};\n\n")

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

    def g_simple(self):
        for r in self.words:
            for a in self.aligns:
                yield self.output(a, r)

    def g_width(self):
        maxw = len(self.words) + 3
        for r in self.words:
            for w in xrange(1, len(self.words) + 3):
                for a in self.aligns:
                    yield self.output('{}{}'.format(a, w), r)

    def g_prec(self):
        maxw = len(self.words) + 3
        for r in self.words:
            for p in xrange(len(self.words) + 3):
                for a in self.aligns:
                    yield self.output('{}.{}'.format(a, p), r)

    def g_wnp(self):
        maxw = len(self.words) + 3
        for r in self.words:
            for w in xrange(1, maxw):
                for p in xrange(maxw):
                    for a in self.aligns:
                        yield self.output('{}{}.{}'.format(a, w, p), r)

# Helpers for the next few classes.
def fib(n):
    if n < 0: raise ValueError("fib() defined only for nonnegative n")
    # 0, 1 handled separately because we don't want the double 1 from the
    # usual fibonacci sequence.
    if n > 0: yield 0
    if n > 1: yield 1
    a, b = 2, 1
    while a < n:
        yield a
        a, b = a+b, a

def integer_test_cases(limit, any_negative):
    numbers = [2**i for i in xrange(limit)]
    # The square brackets on the next line prevent an infinite loop.
    numbers.extend([i-1 for i in numbers])
    numbers.extend(fib(max(numbers)))
    if any_negative:
        numbers.extend([-i for i in numbers])

    # remove duplicates
    numbers = list(set(numbers))

    # 0, 1, -1, ...
    numbers.sort(key=lambda x: abs(x) + (0.5 if x<0 else 0))
    return numbers

class test_sint(TestBlock):
    casetype = '1arg_i'

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

        for n in integer_test_cases(31, True):
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
    def output(spec, val):
        spec = '{:' + spec + '}'
        return '"{}", "{}", {}'.format(spec, spec.format(val), val)

    def g_simple(self):
        aligns = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
        types  = [ '', 'd', 'o', 'x', 'X' ]
        signs  = [ '', '+', '-', ' ' ]
        mods   = [ '', '0', '#', '#0' ]
        widths = [ '', '6', '12' ]

        for n in integer_test_cases(32, False):
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
    def output(val, spec, override_spec=None):
        spec = '{:' + spec + '}'
        if override_spec is None:
            override_spec = spec
        return '"{}", "{}", {}'.format(spec, override_spec.format(val), val)

    def g_simple(self):
        aligns = [ '', '<', '>', '^', '=', 'L<', 'R>', 'C^', 'E=' ]
        types  = [ '', 'e', 'f', 'g', 'E', 'F', 'G' ]
        signs  = [ '', '+', '-', ' ' ]
        mods   = [ '', '0' ]
        wnp    = [ '', '6', '12', '.6', '12.6' ]

        # We don't want test cases to depend on rounding behavior,
        # so we use numbers that are definitely representable in a
        # short form in both decimal and binary floating point.
        numbers = [ 0.0 ]
        for i in range(-5, 21, 2):
            for j in range(i, i+3):
                x = 2.0**i + 2.0**j
                numbers.extend((x,-x))
        numbers = sorted(set(numbers),
                         key=lambda x: abs(x) + (1e-20 if x<0 else 0))

        for n in numbers:
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
                                    yield self.output(n, a+s+m+w,
                                                      '{:' + a+s+m+w + 'g}')
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
