// c++fmt --- Self-contained string formatting library for C++
// Copyright 2012 Zachary Weinberg <zackw@panix.com>.  Use,
// modification, and distribution are subject to the Boost
// Software License, Version 1.0.  See the file LICENSE or
// http://www.boost.org/LICENSE_1_0.txt for detailed terms.

#include <fmt.h>
#include <exception>
#include <numeric>
#include <limits>

#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>

using std::numeric_limits;
using std::string;
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
// sub:   '{' [ index ] [ ':' spec ] '}'
// spec:  [ flags ] [ width ] [ '.' precision ] [ type ]
// flags: [ '#' ] [ '0' ] [ '-' ] [ '+' ] [ ' ' ]  # in any order
// type:  ( 's' | 'c' | 'd' | 'o' | 'x' | 'X' |
//          'e' | 'E' | 'f' | 'F' | 'g' | 'G' )
//
// index, width, precision: [0-9]+
//
// Note especially that the flags have C `printf` semantics, not Python.
//
// Expects to be called with 'p' pointing one past the initial '{'.
// Expects caller to have dealt with doubled {.
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

  while (*p == '#' || *p == '0' || *p == '-' || *p == '+' || *p == ' ') {
    switch(*p) {
    case '#': spec.flag_hash  = true; break;
    case '0': spec.flag_zero  = true; break;
    case '-': spec.flag_minus = true; break;
    case '+': spec.flag_plus  = true; break;
    case ' ': spec.flag_space = true; break;
    }
    p++;
  }

  if (*p >= '0' && *p <= '9') {
    spec.had_width = true;
    spec.width = strtoul(p, &endp, 10);
    if (endp == p) goto error; // this shouldn't happen, but we check anyway
    p = endp;
  }

  if (*p == '.') {
    p++;
    spec.had_prec = true;
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

//
// Per-actual-type formatting subroutines.
//

static const char snprintf_failure[] = "[snprintf failed]";

template <typename T>
static void
do_snprintf(T val, const format_spec &spec, char type, bool error, string &out)
{
  char format[13]; // "%#0-+ *.*llT";
  char *p = format;
  *p++ = '%';
  if (spec.flag_hash)  *p++ = '#';
  if (spec.flag_zero)  *p++ = '0';
  if (spec.flag_minus) *p++ = '-';
  if (spec.flag_plus)  *p++ = '+';
  if (spec.flag_space) *p++ = ' ';
  if (spec.had_width)  *p++ = '*';
  if (spec.had_prec) {
    *p++ = '.';
    *p++ = '*';
  }
  // Slightly dirty trick here: we know by construction that if the type code
  // (which has already been validated) is for an integer, then 'val' is
  // [unsigned] long long.  Otherwise we know that it's double, so no
  // size modifier is required.
  if (type == 'd' || type == 'u' || type == 'o' || type == 'x' || type == 'X') {
    *p++ = 'l';
    *p++ = 'l';
  }
  *p++ = type;
  *p = '\0';

  char buf1[80];
  char *s = buf1;
  if (spec.had_width && spec.had_prec) {
    int nreq = snprintf(buf1, sizeof buf1, format,
                        spec.width, spec.precision, val);
    if (nreq < 0)
      throw snprintf_failure;
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format,
                   spec.width, spec.precision, val) != nreq) {
        delete [] s;
        throw snprintf_failure;
      }
    }
  } else if (spec.had_width) {
    int nreq = snprintf(buf1, sizeof buf1, format, spec.width, val);
    if (nreq < 0)
      throw snprintf_failure;
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format, spec.width, val) != nreq) {
        delete [] s;
        throw snprintf_failure;
      }
    }
  } else if (spec.had_prec) {
    int nreq = snprintf(buf1, sizeof buf1, format, spec.precision, val);
    if (nreq < 0)
      throw snprintf_failure;
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format, spec.precision, val) != nreq) {
        delete [] s;
        throw snprintf_failure;
      }
    }
  } else {
    int nreq = snprintf(buf1, sizeof buf1, format, val);
    if (nreq < 0)
      throw snprintf_failure;
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format, val) != nreq) {
        delete [] s;
        throw snprintf_failure;
      }
    }
  }

  if (error)
    out.append(BEGIN_ERRMSG);
  out.append(s);
  if (error)
    out.append(END_ERRMSG);

  if (s != buf1)
    delete [] s;
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
  do_snprintf(val, spec, type, error, out);
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
  do_snprintf(val, spec, type, error, out);
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
  do_snprintf(val, spec, type, error, out);
}

// This takes unsigned long long instead of the actual character so it
// can do something sensible on overflow.
static void
do_format_char(unsigned long long val,
               const format_spec &spec,
               string &out)
{
  if (spec.type == 'c' && val <= numeric_limits<unsigned char>::max()) {
    // precision and the +, SPC, #, 0 modifiers are ignored; just emit
    // the character with appropriate padding to the left or right.
    if (!spec.flag_minus && spec.had_width && spec.width > 1)
      out.append(spec.width - 1, ' ');

    out.append(1, (unsigned char)val);

    if (spec.flag_minus && spec.had_width && spec.width > 1)
      out.append(spec.width - 1, ' ');

  } else {
    // bounce to do_format_unsigned_int, which will treat this as an error,
    // because spec.type is not one of d,u,o,x,X (or we wouldn't have gotten
    // here in the first place)
    do_format_unsigned_int(val, spec, out);
  }
}

static void
do_format_str(const string &val,
              const format_spec &spec,
              string &out)
{
  if (spec.type != 's')
    out.append(BEGIN_ERRMSG);

  // string truncated to precision, padded to width.
  // +, SPC, #, 0 modifiers ignored.

  size_t slen = val.size();
  if (spec.had_prec && spec.precision < slen)
    slen = spec.precision;

  size_t pad = 0;
  if (spec.had_width && spec.width > slen)
    pad = spec.width - slen;

  if (pad && !spec.flag_minus)
    out.append(pad, ' ');

  out.append(val, 0, slen);

  if (pad && spec.flag_minus)
    out.append(pad, ' ');

  if (spec.type != 's')
    out.append(END_ERRMSG);
}

static void
do_format_cstr(const char *val,
               const format_spec &spec,
               string &out)
{
  if (spec.type != 's')
    out.append(BEGIN_ERRMSG);

  // string truncated to precision, padded to width.
  // +, SPC, #, 0 modifiers ignored.
  // strnlen is not sufficiently portable to use here :(

  size_t slen = 0;
  if (!spec.had_prec)
    slen = strlen(val);
  else
    for (const char *p = val; *p && slen < spec.precision; p++)
      slen++;

  size_t pad = 0;
  if (spec.had_width && spec.width > slen)
    pad = spec.width - slen;

  if (pad && !spec.flag_minus)
    out.append(pad, ' ');

  out.append(val, slen);

  if (pad && spec.flag_minus)
    out.append(pad, ' ');

  if (spec.type != 's')
    out.append(END_ERRMSG);
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
      if (!spec->had_width && !spec->had_prec && !spec->flag_hash
          && !spec->flag_zero && !spec->flag_minus && !spec->flag_plus
          && !spec->flag_space) {
        spec->flag_zero = true;
        spec->had_width = true;
        spec->width = sizeof(void *) * 2;
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
