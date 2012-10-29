// c++fmt --- Self-contained string formatting library for C++
// Copyright 2012 Zachary Weinberg <zackw@panix.com>.  Use,
// modification, and distribution are subject to the Boost
// Software License, Version 1.0.  See the file LICENSE or
// http://www.boost.org/LICENSE_1_0.txt for detailed terms.

#include <fmt.h>
#include <exception>
#include <numeric>
#include <limits>
#include <sstream>

#include <assert.h>
#include <errno.h>   // errno
#include <stdlib.h>  // strtoul
#include <string.h>  // strerror

using std::numeric_limits;
using std::string;
using std::ostringstream;
using std::vector;

namespace fmt {
namespace detail {

// We must avoid writing a direct cast from void * to an integer of a
// different size.  We don't know what size a pointer is, we cannot
// rely on the existence of stdint.h or uintptr_t, and we cannot rely
// on size_t being the same size as a pointer either (thanks ever so
// much, Microsoft).

typedef std::conditional<
  sizeof(void *) == sizeof(unsigned int), unsigned int,
  typename std::conditional<
    sizeof(void *) == sizeof(unsigned long), unsigned long,
    typename std::conditional<
      sizeof(void *) == sizeof(unsigned long long), unsigned long long,
      double // failure marker
    >::type
  >::type
>::type uintptr_t;

static_assert(!std::is_same<uintptr_t, double>::value,
              "failed to detect an integral type with the width of 'void *'");

// Ensure that we can print values of these types without casting.

static_assert(sizeof(size_t) <= sizeof(unsigned long long),
              "'unsigned long long' is not big enough for 'size_t'");
static_assert(sizeof(ptrdiff_t) <= sizeof(long long),
              "'long long' is not big enough for 'ptrdiff_t'");

} // namespace detail

// There is a template below that gets an unwanted "comparison is
// always true" warning when instantiated with an unsigned type (it is
// also instantiated with signed types, and then the comparison is
// necessary).  The necessary incantations to suppress this are
// slightly different for GCC and Clang, and we can't just put both,
// because then each will complain about the other's construct.
// Furrfu.
#if defined __clang__
# define PUSH_WARNINGS_SUPPRESS_TAUTOLOGICAL_COMPARE \
    _Pragma("GCC diagnostic push"); \
    _Pragma("GCC diagnostic ignored \"-Wtautological-compare\"")
# define POP_WARNINGS \
    _Pragma("GCC diagnostic pop")
#elif defined __GNUC__
# define PUSH_WARNINGS_SUPPRESS_TAUTOLOGICAL_COMPARE \
    _Pragma("GCC diagnostic push"); \
    _Pragma("GCC diagnostic ignored \"-Wtype-limits\"")
# define POP_WARNINGS \
    _Pragma("GCC diagnostic pop")
#endif

// Error conditions in the formatter are, in general, reported by
// emitting some sort of placeholder, surrounded by VT-220 reverse
// video escapes.  It is my understanding that these escapes work
// basically everywhere nowadays.

#define BEGIN_ERRMSG "\033[7m"
#define END_ERRMSG "\033[27m"

// Exception recovery.

// The exposed interface guarantees not to throw exceptions under any
// circumstances, which means we have to intercept all exceptions and
// do something sensible.  "Sensible" in this case means: first try to
// insert some sort of placeholder in place of whatever we were
// formatting, and if that fails (perhaps due to OOM), crash.

// We explicitly code catch (...) { std::terminate() } even though
// 'noexcept' is currently defined to call std::terminate if an
// exception is about to escape, for defensiveness against future
// changes to this behavior (noexcept is considered not fully baked).

static const char generic_exception_msg[] = "[exception of unknown type]";

void
formatter::constructor_threw(const char *what) noexcept
{
  try {
    nargs = 0;
    first_errno_spec.reset();
    specs.clear();
    segs.resize(1);
    segs[0] = string(BEGIN_ERRMSG) + what + END_ERRMSG;
  } catch (...) {
    std::terminate();
  }
}

void
formatter::formatsub_threw(const char *what, size_t target) noexcept
{
  try {
    segs.at(target) = string(BEGIN_ERRMSG) + what + END_ERRMSG;
  } catch (...) {
    std::terminate();
  }
}

std::string
formatter::finish_threw(const char *what) noexcept
{
  try {
    return string(BEGIN_ERRMSG) + what + END_ERRMSG;
  } catch (...) {
    std::terminate();
  }
}

// Parse a substitution.
// The simplified grammar we accept is
//
// sub:   '{' [ index | 'm' ] [ ':' spec ] '}'
// spec:  [ mods ] [ width ] [ '.' precision ] [ type ]
// mods:  [ [ fill ] align ] [ sign ] [ '#' ] [ '0' ]
// fill:  <any single character except '{' or '}'>
// align: ( '<' | '>' | '=' )
// sign:  ( '+' | '-' | ' ' )
// type:  ( 's' | 'c' | 'd' | 'o' | 'x' | 'X' |
//          'e' | 'E' | 'f' | 'F' | 'g' | 'G' )
//
// index, width, precision: [0-9]+
//
// Expects to be called with 'p' pointing one past the initial '{'.
// Expects caller to have dealt with doubled {.
// Expects caller to have initialized 'spec'.
// Returns an updated 'p' pointing one past the final '}'.
// If 'spec' has index zero on exit, the spec was ill-formed.

static const char *
parse_subst(const char *p, size_t default_index, format_spec& spec)
{
  spec.arg_index = default_index;

  char *endp;
  if (*p >= '0' && *p <= '9') {
    spec.arg_index = strtoul(p, &endp, 10);
    if (endp == p) goto error; // this shouldn't happen, but we check anyway
    p = endp;
  } else if (*p == 'm') {
    spec.arg_index = format_spec::i_errno;
    p++;
  }

  if (*p == '}') {
    p++;
    return p;
  }

  if (*p != ':')
    goto error;
  p++;

  if (*p == '{' || *p == '\0')
    goto error;
  if (*p == '}') { // {:}
    p++;
    return p;
  }

  // "The presence of a fill character is signaled by the character following
  // it, which must be one of the alignment options. If the second character
  // of |format_spec| is not a valid alignment option, then it is assumed
  // that both the fill character and the alignment option are absent."
  // -- http://docs.python.org/3/library/string.html#format-specification-mini-language
  //
  // Not stated in the text, but evident in the grammar (and the
  // actual behavior of Python), is that if the second character
  // *isn't* a valid alignment option, but the *first* character is,
  // then the first character is an alignment option and the fill
  // defaults to a space character.

  // at this point we know that p[0] is not NUL, but p[1] still might be.
  if (p[1] == '\0')
    goto error;
  if (p[1] == '<' || p[1] == '>' || p[1] == '=' || p[1] == '^') {
    spec.align = p[1];
    spec.fill = p[0];
    p += 2;
  } else if (p[0] == '<' || p[0] == '>' || p[0] == '=' || p[0] == '^') {
    spec.align = p[0];
    spec.fill = ' ';
    p += 1;
  }

  // Unlike printf, the sign, alternate-form, and zero-fill modifiers
  // may _not_ appear in any order.
  if (*p == '+' || *p == '-' || *p == ' ') {
    spec.sign = *p;
    p++;
  }
  if (*p == '#') {
    spec.alternate_form = true;
    p++;
  }
  if (*p == '0') {
    // Python documents '0' right before the width as shorthand for an
    // '0=' alignment modifier.  If you have both '0' and a
    // conflicting alignment modifier, Python's actual behavior is not
    // internally consistent.  We avoid the issue by treating '0' plus
    // an explicit alignment modifier as an error.
    if (spec.align != '\0')
      goto error;
    spec.align = '=';
    spec.fill = '0';
    p++;
  }

  if (*p >= '0' && *p <= '9') {
    spec.has_width = true;
    spec.width = strtoul(p, &endp, 10);
    if (endp == p) goto error; // this shouldn't happen, but we check anyway
    p = endp;
  }

  if (*p == '.') {
    p++;
    spec.has_precision = true;
    spec.precision = strtoul(p, &endp, 10);
    if (endp == p) goto error; // this case _can_ happen
    p = endp;
  }

  if (*p == 's' || *p == 'c' ||
      *p == 'd' || *p == 'o' || *p == 'x' || *p == 'X' ||
      *p == 'e' || *p == 'E' || *p == 'f' || *p == 'F' ||
      *p == 'g' || *p == 'G') {
    spec.type = *p;
    p++;
  }

  if (*p == '}') {
    p++;
    return p;
  }

 error:
  spec.reset();
  while (*p != '\0' && *p != '}')
    p++;
  if (*p == '}')
    p++;
  return p;
}

// Parse a format string.  Python is picky about close curly braces
// being doubled even if there is no possibility of ambiguity, so we
// follow suit.  Python throws exceptions on ill-formed strings; in
// the service of never throwing exceptions from this code, we
// just reverse-video the offending construct and continue.

void
formatter::parse_format_string(const char *str)
{
  segs.reserve(nargs * 2 + 1);
  specs.resize(nargs);

  string cseg;
  size_t default_index = 0;
  vector<format_spec> extras;  // Used only if there is more than one spec
                               // referring to the same argument index.

  for (const char *p = str; *p; ) {
    if (*p == '{') {
      if (*(p+1) == '{') {
        cseg.append(1, *p);
        p += 2;
      } else {
        format_spec spec;
        const char *endp = parse_subst(p+1, default_index, spec);
        // N.B. format_spec::i_invalid and ::i_errno are guaranteed
        // to be larger than specs.size() (being size_t(-1) and
        // size_t(-2) respectively).
        if (spec.arg_index >= specs.size() &&
            spec.arg_index != format_spec::i_errno) {
          cseg.append(BEGIN_ERRMSG);
          cseg.append(p, endp - p);
          cseg.append(END_ERRMSG);
        } else {
          segs.push_back(cseg);
          segs.push_back(string());
          cseg.clear();

          spec.target = segs.size() - 1;
          format_spec &s = (spec.arg_index == format_spec::i_errno
                            ? first_errno_spec
                            : specs[spec.arg_index]);
          if (s.arg_index == format_spec::i_invalid)
            // First spec with this argument index; just insert it.
            s = spec;
          else
            extras.push_back(spec);
        }
        if (spec.arg_index == default_index)
          default_index++;
        p = endp;
      }
    } else if (*p == '}') {
      if (*(p+1) == '}') {
        cseg.append(1, *p);
        p += 2;
      } else {
        cseg.append(BEGIN_ERRMSG "}" END_ERRMSG);
        p++;
      }
    } else {
      cseg.append(1, *p);
      p++;
    }
  }
  segs.push_back(cseg);

  // This is quadratic in chain length, but chains of more than one or
  // two elements are unlikely to happen, so let's not worry about it
  // for now.
  if (extras.size() > 0) {
    for (auto s = extras.begin(); s != extras.end(); s++) {
      specs.push_back(*s);
      size_t sind = specs.size() - 1;
      format_spec *other = (s->arg_index == format_spec::i_errno
                            ? &first_errno_spec
                            : &specs[s->arg_index]);

      while (other->next_this_index != format_spec::i_invalid)
        other = &specs[other->next_this_index];
      other->next_this_index = sind;
    }
  }
}

//
// Per-actual-type formatting subroutines.
//

static void
do_alignment(const string &s, const format_spec &spec,
             char type, bool error, string &out)
{
  if (error)
    out.append(BEGIN_ERRMSG);

  // is alignment actually required?
  if (!spec.has_width || spec.width <= s.size())
    out.append(s);
  else {
    size_t pad = spec.width - s.size();
    char align = spec.align;

    if (align == '\0')
      align = type == 's' ? '<' : '>';

    switch (align) {
    case '<':
      out.append(s);
      out.append(pad, spec.fill);
      break;

    case '>':
      out.append(pad, spec.fill);
      out.append(s);
      break;

    case '^':
      // If there are an odd number of padding characters required,
      // put one more on the right.
      out.append(pad/2, spec.fill);
      out.append(s);
      out.append(pad/2 + pad%2, spec.fill);
      break;

    case '=': {
      unsigned int leading = 0;
      if (type != 's' && type != 'c' && (s[0] == '-' || spec.sign != '-'))
        leading = 1;
      if (spec.alternate_form && (type == 'o' || type == 'x' || type == 'X'))
        leading += 2;

      out.append(s.substr(0, leading));
      out.append(pad, spec.fill);
      out.append(s.substr(leading));
    } break;

    default:
      throw "impossible alignment specifier";
    }
  }

  if (error)
    out.append(END_ERRMSG);
}

// The heavy lifting on numeric formatting is done by a stringstream.
// However, the iostreams feature set is inadequate to handle all of
// Python's alignment, explicit sign, and explicit base features, so
// we do that part by hand.

template <typename T>
static void
do_numeric_format(T val, const format_spec &spec,
                  char type, bool error, string &out)
{
  using std::ios_base;

  ostringstream os;
  os.exceptions(ios_base::failbit|ios_base::badbit|ios_base::eofbit);

  if (spec.has_precision)
    os.precision(spec.precision);
  if (spec.alternate_form)
    os.setf(ios_base::showpoint); // we do showbase ourselves

  // "general" style is the default
  if (type == 'e' || type == 'E') {
    os.setf(ios_base::scientific, ios_base::floatfield);
  } else if (type == 'f' || type == 'F') {
    os.setf(ios_base::fixed, ios_base::floatfield);
  }

  // decimal is the default
  if (type == 'o') {
    os.setf(ios_base::oct, ios_base::basefield);
  } else if (type == 'x' || type == 'X') {
    os.setf(ios_base::hex, ios_base::basefield);
  }

  if (type == 'E' || type == 'F' || type == 'G' || type == 'X') {
    os.setf(ios_base::uppercase);
  }

  // iostreams can mark positive values with '+' but not with a space,
  // so we do it ourselves in both cases
  PUSH_WARNINGS_SUPPRESS_TAUTOLOGICAL_COMPARE;
  if (val >= 0 && spec.sign != '-')
    os << spec.sign;
  POP_WARNINGS;

  // iostreams 'o' alternate form is '0nnnn' not '0onnnn'
  if (spec.alternate_form) {
    if (type == 'o')
      os << "0o";
    else if (type == 'x')
      os << "0x";
    else if (type == 'X')
      os << "0X";
  }

  os << val;

  do_alignment(os.str(), spec, type, error, out);
}

static void
do_format_unsigned_int(unsigned long long val,
                       const format_spec &spec,
                       string &out)
{
  char type = spec.type;
  bool error = false;
  if (type != 'd' && type != 'u' && type != 'o' &&
      type != 'x' && type != 'X') {
    type = 'u';
    error = true;
  }
  do_numeric_format(val, spec, type, error, out);
}

static void
do_format_signed_int(long long val,
                     const format_spec &spec,
                     string &out)
{
  char type = spec.type;
  bool error = false;
  if (type != 'd' && type != 'u' && type != 'o' &&
      type != 'x' && type != 'X') {
    type = 'd';
    error = true;
  }
  do_numeric_format(val, spec, type, error, out);
}

static void
do_format_float(double val,
                const format_spec &spec,
                string &out)
{
  char type = spec.type;
  bool error = false;
  if (type != 'e' && type != 'E' && type != 'f' && type != 'F' &&
      type != 'g' && type != 'G') {
    type = 'g';
    error = true;
  }
  do_numeric_format(val, spec, type, error, out);
}

// This takes unsigned long long instead of the actual character so it
// can do something sensible on overflow.
static void
do_format_char(unsigned long long val,
               const format_spec &spec,
               string &out)
{
  if (spec.type == 'c' && val <= numeric_limits<unsigned char>::max())
    // precision and most modifiers are ignored; just emit the
    // character with appropriate padding.
    do_alignment(string(1, val), spec, spec.type, false, out);

  else
    // format as unsigned decimal, with error markers.
    do_numeric_format(val, spec, 'u', true, out);
}

static void
do_format_str(const string &val,
              const format_spec &spec,
              string &out)
{
  // Truncate to precision, pad to width.
  if (!spec.has_precision)
    do_alignment(val, spec, 's', spec.type != 's', out);
  else
    do_alignment(val.substr(0, spec.precision),
                 spec, 's', spec.type != 's', out);
}

static void
do_format_cstr(const char *val,
               const format_spec &spec,
               string &out)
{
  // Truncate to precision, pad to width.
  // In the with-precision case, we can't just convert directly to a
  // C++ string because the (const char *, size_t) constructor does
  // *not* look for a nul-terminator.
  // strnlen is not sufficiently portable to use here :(

  if (!spec.has_precision)
    do_alignment(val, spec, 's', spec.type != 's', out);
  else {
    size_t slen = 0;
    for (const char *p = val; *p && slen < spec.precision; p++)
      slen++;

    do_alignment(string(val, slen), spec, 's', spec.type != 's', out);
  }
}

void
formatter::format_sub(size_t i, unsigned char val) noexcept
{
  if (i >= specs.size())
    return; // argument not used (probably a can't-happen)
  format_spec *spec = &specs[i];
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 'c';

      switch (spec->type) {
      case 'c':
      default:
        do_format_char(val, *spec, segs.at(spec->target));
        break;

      case 'd':
      case 'u':
      case 'o':
      case 'x':
      case 'X':
        do_format_unsigned_int(val, *spec, segs.at(spec->target));
        break;
      }

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

void
formatter::format_sub(size_t i, long long val) noexcept
{
  if (i >= specs.size())
    return; // argument not used (probably a can't-happen)
  format_spec *spec = &specs[i];
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 'd';

      switch (spec->type) {
      case 'c':
        do_format_char(val, *spec, segs.at(spec->target));
        break;

      case 'd':
      default:
        do_format_signed_int(val, *spec, segs.at(spec->target));
        break;

      case 'u':
      case 'o':
      case 'x':
      case 'X':
        do_format_unsigned_int(val, *spec, segs.at(spec->target));
        break;
      }

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

void
formatter::format_sub(size_t i, unsigned long long val) noexcept
{
  if (i >= specs.size())
    return; // argument not used (probably a can't-happen)
  format_spec *spec = &specs[i];
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 'u';

      switch (spec->type) {
      case 'c':
        do_format_char(val, *spec, segs.at(spec->target));
        break;

      case 'd':
        do_format_signed_int(val, *spec, segs.at(spec->target));
        break;

      case 'u':
      case 'o':
      case 'x':
      case 'X':
      default:
        do_format_unsigned_int(val, *spec, segs.at(spec->target));
        break;
      }

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

// Raw pointers are printed in lowercase hexadecimal with an
// appropriate number of leading zeros, unless we are told otherwise.
void
formatter::format_sub(size_t i, const void *val) noexcept
{
  if (i >= specs.size())
    return; // argument not used (probably a can't-happen)
  format_spec *spec = &specs[i];
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 'x';
      if (!spec->has_width) {
        spec->has_width = true;
        spec->width = sizeof(void *) * 2;
        spec->fill = '0';
        spec->align = '>';
      }
      do_format_unsigned_int(detail::uintptr_t(val), *spec,
                             segs.at(spec->target));

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

void
formatter::format_sub(size_t i, double val) noexcept
{
  if (i >= specs.size())
    return; // argument not used (probably a can't-happen)
  format_spec *spec = &specs[i];
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 'g';
      do_format_float(val, *spec, segs.at(spec->target));

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

void
formatter::format_sub(size_t i, const char *val) noexcept
{
  // only this function has to worry about errno.
  if (i >= specs.size() && i != format_spec::i_errno)
    return; // argument not used (probably a can't-happen)
  format_spec *spec = (i == format_spec::i_errno
                       ? &first_errno_spec : &specs[i]);
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 's';
      do_format_cstr(val, *spec, segs.at(spec->target));

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

void
formatter::format_sub(size_t i, const string &val) noexcept
{
  if (i >= specs.size())
    return; // argument not used (probably a can't-happen)
  format_spec *spec = &specs[i];
  if (spec->arg_index == format_spec::i_invalid)
    return; // argument not used
  for (;;) {
    assert(spec->arg_index == i);

    try {
      if (spec->type == '\0')
        spec->type = 's';
      do_format_str(val, *spec, segs.at(spec->target));

    } catch (std::exception const& e) {
      formatsub_threw(e.what(), spec->target);
    } catch (const char *what) {
      formatsub_threw(what, spec->target);
    } catch (...) {
      formatsub_threw(generic_exception_msg, spec->target);
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

// Public interface.

formatter::formatter(size_t nargs_, const char *msg) noexcept
  : nargs(nargs_)
{
  // Save 'errno' before doing _anything_ else.  This won't be good
  // enough if evaluation of the parent argument list clobbered it,
  // but that's a "you get to keep both pieces" scenario.
  // TODO: Needs Windows smarts.
  int saved_errno = errno;

  try {
    parse_format_string(msg);

    // If we're asked to print strerror(errno), take care of that now.
    if (first_errno_spec.target != format_spec::i_invalid) {
      format_sub(format_spec::i_errno, strerror(saved_errno));
    }

  } catch (std::exception const& e) {
    constructor_threw(e.what());

  } catch (const char *what) {
    constructor_threw(what);

  } catch (...) {
    constructor_threw(generic_exception_msg);
  }
}

string
formatter::finish() noexcept
{
  try {
    return std::accumulate(segs.begin(), segs.end(), string(""));

  } catch (std::exception const& e) {
    return finish_threw(e.what());

  } catch (const char *what) {
    return finish_threw(what);

  } catch (...) {
    return finish_threw(generic_exception_msg);
  }
}

} // namespace fmt

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End: