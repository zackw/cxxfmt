// Test skeleton for cxxfmt.  This program is compiled, potentially
// several times, with code injected by the Python test generators,
// and run.  It emits per-test status messages which the Python
// harness will process and convert to human-readable failure reports.

#include <string>
#include <vector>
#include <iostream>
#include <fmt.h>

using std::string;
using std::vector;
using std::cout;
using std::endl;
using fmt::format;

namespace {

// Note: we intentionally use std::endl instead of '\n' to get cout
// flushed after each line of output; the program is normally run
// with cout pointing at a pipe, and the other end of the pipe wants
// as-soon-as-possible notification of the results of each test.

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

// more case_ structures here

static void
report(string const& label, const char *spec,
       string const& got, const char *expected)
{
  if (got == expected) {
    if (0)
      cout << "+\t" << label << '\t' << spec << '\t'
           << expected << endl;
  } else {
    cout << "-\t" << label << '\t' << spec << '\t'
         << expected << '\t' << got << endl;
  }
}

template <typename case_1arg>
static void
process(string const& label, const case_1arg *cases, size_t n)
{
  for (const case_1arg *c = cases; c < cases+n; c++) {
    string got(format(c->spec, c->val));
    report(label, c->spec, got, c->expected);
  }
}

// more process_ overloads here

struct i_tblock { virtual void operator()(const char *) const = 0; };

template <typename case_1arg>
struct tblock : i_tblock
{
  template <size_t N>
  tblock(const char *tag_, const case_1arg (&cases_)[N])
    : tag(tag_), cases(cases_), n(N)
  {}

  virtual void operator()(const char *label_) const
  {
    string label(label_);
    label += '\t';
    label += tag;
    cout << ":\t" << label << '\t' << n << endl;
    process(label, cases, n);
  }

private:
  const char *tag;
  const case_1arg *cases;
  size_t n;
};

#include "testcases.inc"

} // anonymous namespace

int
main()
{
#ifndef COMPILER_NAME
#define COMPILER_NAME "unknown"
#endif

  for (size_t i = 0; i < n_tblocks; i++)
    (*tblocks[i])(COMPILER_NAME);
  return 0;
}

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End:
