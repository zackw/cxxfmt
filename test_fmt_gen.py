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
    if len(name) == 0: return name
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
        self.symbol = tosymbol(caseprinter.__name__)

        if self.symbol in self.allcasetypes:
            raise RuntimeError("duplicate casetype name: " + self.name)
        self.allcasetypes[self.symbol] = self

    def __cmp__(self, other):
        return cmp(self.symbol, other.symbol)

    def write_case(self, outf, args):
        try:
            outf.write("  { " + self.caseprinter(*args) + " },\n")
        except:
            sys.stderr.write("\n*** args: " + repr(args) + "\n")
            raise

    def write_decl(self, outf):
        outf.write("struct {}\n".format(self.symbol))
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
    if '{' not in spec:
        spec = '{:' + spec + '}'
    if '{' not in override_spec:
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
    if len(spec) == 0 or ('{' not in spec and spec[-1] not in "eEfFgG"):
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
    if len(spec) > 0 and spec[-1] in "cdoxX}":
        val = ord(val)
    ospec = spec
    return case_a1(spec, ospec, val, cval)

@caseprint( ("const char *", "const char *", "const char *") )
def case_a3_s_s_s(spec, v1, v2, v3, exp=None):
    if exp is None:
        exp = spec.format(v1, v2, v3)
    return (json.dumps(spec) + ", " +
            json.dumps(exp) + ", " +
            json.dumps(v1) + ", " +
            json.dumps(v2) + ", " +
            json.dumps(v3))

class TestProcess1(object):
    """Generate a function to process a single subtest of a particular
       casetype."""
    template = textwrap.dedent("""\
          static bool
          process1_{0}(const {1}& c)
          {{
          {2}
            return process1_T(c.spec, c.expected, {3});
          }}

          """)

    all_process1_fns = {}

    def __init__(self, casetype, name, body):
        self.casetype = casetype
        self.name = name
        self.symbol = tosymbol(name)
        self.body = redent(body, 2)

        if self.symbol in self.all_process1_fns:
            raise RuntimeError("duplicate process1 symbol: \"{}\""
                               .format(self.symbol))
        self.all_process1_fns[self.symbol] = self

    def __cmp__(self, other):
        return (cmp(self.casetype, other.casetype) or
                cmp(self.symbol, other.symbol))

    def write_fn(self, outf):
        vs = ", ".join("v"+str(i) for i in range(len(self.casetype.vtypes)))
        outf.write(self.template.format(self.symbol,
                                        self.casetype.symbol,
                                        self.body,
                                        vs))

class TestProcess(object):
    """Generate a function to process an entire block of tests.
       This is used for test blocks that are too complicated to
       fit the loop-over-a-big-POD-array-of-subtests paradigm."""
    template = textwrap.dedent("""\
        {2}static bool
        process{0}(const char *tag{1})
        {{
          if (!quiet)
            cout << "test " << tag << "..." << flush;
          bool success = true;
        {3}
          if (!quiet) {{
            if (success)
              cout << " ok\\n";
            else
              cout << '\\n'; // failures printed already
          }}
          return success;
        }}
        """)

    all_process_fns = {}

    def __init__(self, name, args, targs, body):
        symbol = tosymbol(name)
        if symbol != "": symbol = "_"+symbol
        if symbol in self.all_process_fns:
            raise RuntimeError("duplicate process1 symbol: \"{}\""
                               .format(self.symbol))
        self.all_process_fns[symbol] = self

        if isinstance(args, str):
            sep = ",\n" + " "*(len(symbol)+8)
            args = sep + args
        elif args is not None and len(args) > 0:
            sep = ",\n" + " "*(len(symbol)+8)
            args = sep + sep.join(args)
        else:
            args = ""

        if isinstance(targs, str):
            targs = "template <" + targs + ">\n"
        elif targs is not None and len(targs) > 0:
            targs = "template <" + ", ".join(targs) + ">\n"
        else:
            targs = ""

        self.symbol = symbol
        self.args = args
        self.targs = targs
        self.body = redent(body, 2)

    def write_fn(self, outf):
        outf.write(self.template.format(self.symbol, self.args, self.targs,
                                        self.body))

process_generic = TestProcess("",
                              ("const caseT (&cases)[n]",
                               "bool (*process1)(const caseT&)"),
                              ("typename caseT", "size_t n"),
                              """\
  for (const caseT* c = cases; c < cases+n; c++)
    success &= process1(*c);
""")

class TestBlock(object):
    """One block of tests.  All tests in a block share the same
       'casetype' and 'process1'."""
    allblocks = {}

    def __init__(self, name, casetype, process1, blocksym):
        if name in self.allblocks:
            raise RuntimeError("duplicate test block name: " + name)
        self.allblocks[name] = self

        if process1 is not None:
            if casetype != process1.casetype:
                raise RuntimeError("casetype mismatch: self={}, process1={}"
                                   .format(casetype.symbol,
                                           process1.casetype.symbol))
        self.casetype = casetype
        self.process1 = process1
        self.name = name
        self.blocksym = blocksym

    def __cmp__(self, other):
        # These are sorted strictly by name because that makes the verbose
        # test-runner output look better.
        return cmp(self.name, other.name)

    def write_cases(self, outf):
        pass

    def write_process_call(self, outf):
        if self.process1 is None:
            p1sym = "generic"
        else:
            p1sym = self.process1.symbol
        outf.write('  success &= process("{0}", tc_{1}, process1_{2});\n'
                   .format(self.name, self.blocksym, p1sym))

class GenTB(TestBlock):
    """A block of tests generated from a generator function."""

    def __init__(self, name, casetype, generator):
        TestBlock.__init__(self, name, casetype, None, tosymbol(name))
        self.generator = generator

    def write_cases(self, outf):
        outf.write("const {0} tc_{1}[] = {{\n"
                   .format(self.casetype.symbol, self.blocksym))
        count = 0
        for case in self.generator():
            self.casetype.write_case(outf, case)
            count += 1
        outf.write("}};\n// {} cases\n\n".format(count))


class VarTB(TestBlock):
    """A block of tests which reuses an existing block with a different
       'process1' function."""

    def __init__(self, depblock, process1):
        TestBlock.__init__(self, depblock.name + " (" + process1.name + ")",
                           depblock.casetype, process1, depblock.blocksym)

class SpecialTB(TestBlock):
    """A block of tests implemented using a custom 'process' function.
       You are responsible for setting up whatever infrastructure it needs."""

    def __init__(self, name, body):
        TestBlock.__init__(self, name, case_a0, None, tosymbol(name))
        self.processor = TestProcess(name, (), (), body)

    def write_process_call(self, outf):
        outf.write('  success &= process{1}("{0}");\n'
                   .format(self.name, self.processor.symbol))

def testgen(casetype, name):
    """Decorator to facilitate creation of GenTBs from testcase
       generator functions."""
    return lambda fn: GenTB(name, casetype, fn)

def special_testgen(name):
    """Decorator to facilitate creation of SpecialTBs from testcase
       generator functions.  In this case 'fn' is expected to return
       the body of the custom process function as a string."""
    return lambda fn: SpecialTB(name, fn())

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

@special_testgen("exceptions thrown by conversion methods")
def test_exceptions_in_conversion():
    obj_template = ("struct {label} {{\n"
                    "  {method} {{ throw {obj}; }}\n"
                    "}};\n")
    call_template = (
        "success &= process1_T(\"{label} {{}}\",\n"
        "                      \"{label} \\x1b[7m{expect}\\x1b[27m\",\n"
        "                      {label}());\n")

    methods = [ { "where":  "op_string",
                  "method": "operator string() const" },
                { "where":  "str_sig1",
                  "method": "const char* str() const" },
                { "where":  "str_sig2",
                  "method": "string str() const" },
                { "where":  "str_sig3",
                  "method": "const string& str() const" },
                { "where":  "c_str",
                  "method": "const char* c_str() const" },
                { "where":  "what",
                  "method": "const char* what() const" } ]

    crockery = [ { "what":   "logic_error",
                   "obj":    "logic_error(\"{label}\")",
                   "expect": "{label}" },
                 { "what":   "exception",
                   "obj":    "exception()",
                   "expect": "std::exception" },
                 { "what":   "string",
                   "obj":    "\"{label}\"",
                   "expect": "{label}" },
                 { "what":   "unidentifiable",
                   "obj":    "42",
                   "expect": "[exception of unknown type]" } ]

    objects = []
    calls = []

    for m in methods:
        for c in crockery:
            mc = { "where":  m['where'],
                   "method": m['method'],
                   "what":   c['what'],
                   "obj":    c['obj'],
                   "expect": c['expect'] }
            mc['label'] = "tf_{where}_{what}".format(**mc)
            mc['obj'] = mc['obj'].format(**mc)
            mc['expect'] = mc['expect'].format(**mc)

            objects.append(obj_template.format(**mc))
            calls.append(call_template.format(**mc))

    return "".join(objects) + "\n" + "".join(calls)

@special_testgen("formatting enums")
def test_format_enum():
    return """\
  enum X { A = 0, B = 1, C = 3, D = -1, E = 0x10001 };
  X a = A, b = B, c = C, d = D, e = E;
  success &= process1_T("A {}", "A 0", a);
  success &= process1_T("B {}", "B 1", b);
  success &= process1_T("C {}", "C 3", c);
  success &= process1_T("D {}", "D -1", d);
  success &= process1_T("E {:#x}", "E 0x10001", e);
"""

@special_testgen("formatting pointers")
def test_format_enum():
    return """\
  void *foo     = 0;
  struct T *bar = (struct T*)0x10001;
  success &= process1_T("foo {:08x}", "foo 00000000", foo);
  success &= process1_T("bar {:08x}", "bar 00010001", bar);
  success &= process1_T("foo {:#1o}", "foo 0o0", foo);
  success &= process1_T("bar {:#1o}", "bar 0o200001", bar);
  success &= process1_T("foo {0:#1o} {0:1d}", "foo 0o0 0", foo);
  success &= process1_T("bar {0:#1o} {0:1d}", "bar 0o200001 65537", bar);
  // The default pointer formatting depends on the size of a pointer.
  static_assert(sizeof(void *)==4 ||
                sizeof(void *)==8, "need specialization for your pointer size");
  if (sizeof(void *) == 4) {
    success &= process1_T("foo {}", "foo 00000000", foo);
    success &= process1_T("bar {}", "bar 00010001", bar);
  } else if (sizeof(void *) == 8) {
    success &= process1_T("foo {}", "foo 0000000000000000", foo);
    success &= process1_T("bar {}", "bar 0000000000010001", bar);
  }
"""

@special_testgen("printing strerror(errno)")
def test_errno():
    call_template = (
        "errno = {0};\n"
        "success &= process1_T(\"{1}\",\n"
        "                  format(\"{2}\", 42, strerror({0})).c_str(), 42);\n")

    # these errno constants should exist everywhere
    errnos = [ "EACCES", "ENOENT", "EINVAL", "EEXIST" ]

    formats = [ ("{m}",          "{1}"),
                ("{m:<50}",      "{1:<50}"),
                ("{0} {m}",      "{0} {1}"),
                ("{m} {0}",      "{1} {0}"),
                ("{m} {0} {m}",  "{1} {0} {1}"),
                ("{0} {m} {0}",  "{0} {1} {0}"),
                ("{m}{0}{m}{0}", "{1}{0}{1}{0}"),
                ("{m}{m}{0}{0}", "{1}{1}{0}{0}") ]

    return "\n".join(call_template.format(e, f[0], f[1])
                     for e in errnos
                     for f in formats)

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

process1_str_stdstr = TestProcess1(case_a1_cs,
                                   "std::string",
                                   "string v0(c.v0);")

test_str_stdstr = VarTB(test_str, process1_str_stdstr)
test_str_stdexc = VarTB(test_str, TestProcess1(case_a1_cs,
                                               "std::exception",
                                               "logic_error v0(c.v0);"))
test_str_csconv = VarTB(test_str, TestProcess1(case_a1_cs,
                                               "conversion to char*",
                                               """\
                          struct ts {
                            const char* s;
                            ts(const char* s_) : s(s_) {}
                            operator const char* () const { return s; }
                          };
                          ts v0(c.v0);"""))
test_str_csstr  = VarTB(test_str, TestProcess1(case_a1_cs,
                                               "str() method (char *)",
                                               """\
                          struct ts {
                            const char* s;
                            ts(const char *s_) : s(s_) {}
                            const char* str() const { return s; }
                          };
                          ts v0(c.v0);"""))
test_str_cscstr = VarTB(test_str, TestProcess1(case_a1_cs,
                                               "c_str() method",
                                               """\
                          struct ts {
                            const char *s;
                            ts(const char *s_) : s(s_) {}
                            const char* c_str() const { return s; }
                          };
                          ts v0(c.v0);"""))
test_str_ssconv = VarTB(test_str, TestProcess1(case_a1_cs,
                                               "conversion to std::string",
                                               """\
                          struct ts {
                            const char *s;
                            ts(const char *s_) : s(s_) {}
                            operator string() const { return string(s); }
                          };
                          ts v0(c.v0);"""))
test_str_ssstr  = VarTB(test_str, TestProcess1(case_a1_cs,
                                               "str() method (std::string)",
                                               """\
                          struct ts {
                            const char *s;
                            ts(const char *s_) : s(s_) {}
                            string str() const { return string(s); }
                          };
                          ts v0(c.v0);"""))

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

test_char_uchar = VarTB(test_char, TestProcess1(case_a1_c,
                                                "unsigned",
                                                "unsigned char v0 = c.v0;"))
test_char_schar = VarTB(test_char, TestProcess1(case_a1_c,
                                                "signed",
                                                "signed char v0 = c.v0;"))

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
test_float_dbl = VarTB(test_float, TestProcess1(case_a1_f,
                                                "double",
                                                "double v0 = c.v0;"))

@testgen(case_a1_f, "multiple specs one argument (float)")
def test_2s1a_float():
    for n in float_test_cases():
        yield (n, "{0:12.6e} {0:<+4f} {0:.6g}")

@testgen(case_a1_is, "multiple specs one argument (signed int)")
def test_2s1a_sint():
    for n in integer_test_cases(2**8, True):
        yield (n, "{0:d} {0:o} {0:x}")

@testgen(case_a1_iu, "multiple specs one argument (unsigned int)")
def test_2s1a_uint():
    for n in integer_test_cases(2**8, False):
        yield (n, "{0:d} {0:o} {0:x}")

@testgen(case_a1_c, "multiple specs one argument (char)")
def test_2s1a_char():
    for c in "a!'0\t":
        yield (c, "{0:c} {0:o}")

@testgen(case_a1_cs, "multiple specs one argument (str)")
def test_2s1a_str():
    for c in [ "", "i", "of", "sis", "fice", "drisk" ]:
        yield (c, "{0:s} {0:<5} {0:>10s} {0:^15}")

test_2s1a_stdstr = VarTB(test_2s1a_str, process1_str_stdstr)

@testgen(case_a3_s_s_s, "exceptions thrown internally")
def test_exceptions_internal():
    # We have a custom ::operator new which will throw bad_alloc if it
    # is asked to allocate more than 1152 bytes.  (None of the other
    # tests need to allocate more than about 550 bytes at once.)  We
    # use this to trigger exceptions at tailored locations.  In order
    # to make it interesting we require more than one substitution
    # slot.
    tick = "tick"
    boom = "boom"*(1156/4)
    ping = "ping"*(1156/10)
    dent = "\x1b[7mstd::bad_alloc\x1b[27m"

    return [ ( boom, "", "", "", dent ),

             ( "{} {} {}", tick, tick, tick, tick+" "+tick+" "+tick ),

             ( "{} {} {}", boom, tick, tick, dent+" "+tick+" "+tick ),
             ( "{} {} {}", tick, boom, tick, tick+" "+dent+" "+tick ),
             ( "{} {} {}", tick, tick, boom, tick+" "+tick+" "+dent ),

             ( "{} {} {}", tick, boom, boom, tick+" "+dent+" "+dent ),
             ( "{} {} {}", boom, tick, boom, dent+" "+tick+" "+dent ),
             ( "{} {} {}", boom, boom, tick, dent+" "+dent+" "+tick ),

             ( "{} {} {}", boom, boom, boom, dent+" "+dent+" "+dent ),

             ( "{} {} {}", ping, tick, tick, ping+" "+tick+" "+tick ),
             ( "{} {} {}", tick, ping, tick, tick+" "+ping+" "+tick ),
             ( "{} {} {}", tick, tick, ping, tick+" "+tick+" "+ping ),

             # two pings one tick may or may not throw an exception
             # depending on allocator behavior, so we don't try it

             ( "{} {} {}", ping, ping, ping, dent ),
           ]


skeleton_0 = r"""// Tester for cxxfmt.

// Copyright 2012, 2013 Zachary Weinberg <zackw@panix.com>.
// Use, modification, and distribution are subject to the
// Boost Software License, Version 1.0.  See the file LICENSE
// or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

// This program was generated by test_fmt_gen.py.  DO NOT EDIT.
// Edit test_fmt_gen.py instead.

#include <fmt.h>

#include <cstring>
#include <cstdlib>
#include <iostream>
#include <new>
#include <stdexcept>

using std::cout;
using std::exception;
using std::logic_error;
using std::flush;
using std::strcmp;
using std::string;
using fmt::format;

// see test_exceptions_internal
void *
operator new(size_t n)
{
  if (n > 1152)
    throw std::bad_alloc();
  void* v = std::malloc(n);
  if (!v) throw std::bad_alloc();
  return v;
}
void
operator delete(void *p)
{
  std::free(p);
}

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
MAKE_HAS_TRAIT(v2);
MAKE_HAS_TRAIT(v3);

template <typename... TS>
static bool
process1_T(const char *spec, const char *expected, TS&&... vs)
{
  string got(format(spec, vs...));
  return report(spec, got, expected);
}

template <typename case_,
          typename = typename std::enable_if<!has_v0<case_>::value>::type>
static bool
process1_generic(const case_& c)
{
  string got(format(c.spec));
  return report(c.spec, got, c.expected);
}

template <typename case_,
          typename = typename std::enable_if<has_v0<case_>::value>::type,
          typename = typename std::enable_if<!has_v1<case_>::value>::type>
static bool
process1_generic(const case_& c)
{
  return process1_T(c.spec, c.expected, c.v0);
}

template <typename case_,
          typename = typename std::enable_if<has_v0<case_>::value>::type,
          typename = typename std::enable_if<has_v1<case_>::value>::type,
          typename = typename std::enable_if<!has_v2<case_>::value>::type>
static bool
process1_generic(const case_& c)
{
  return process1_T(c.spec, c.expected, c.v0, c.v1);
}

template <typename case_,
          typename = typename std::enable_if<has_v0<case_>::value>::type,
          typename = typename std::enable_if<has_v1<case_>::value>::type,
          typename = typename std::enable_if<has_v2<case_>::value>::type,
          typename = typename std::enable_if<!has_v3<case_>::value>::type>
static bool
process1_generic(const case_& c)
{
  return process1_T(c.spec, c.expected, c.v0, c.v1, c.v2);
}

"""

skeleton_2 = r"""
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

        p1s = TestProcess1.all_process1_fns.values()
        p1s.sort()
        for p in p1s: p.write_fn(outf)

        ps = TestProcess.all_process_fns.values()
        ps.sort()
        for p in ps: p.write_fn(outf)

        outf.write(skeleton_2)
        for b in blocks: b.write_process_call(outf)
        outf.write(skeleton_3)

assert __name__ == '__main__'
main()
