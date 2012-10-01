// c++fmt --- Self-contained string formatting library for C++
// Copyright 2012 Zachary Weinberg <zackw@panix.com>.  Use,
// modification, and distribution are subject to the Boost
// Software License, Version 1.0.  See the file LICENSE or
// http://www.boost.org/LICENSE_1_0.txt for detailed terms.

#include <fmt.h>
#include <exception>
#include <limits>
#include <stdlib.h>
#include <stdio.h>

using std::string;
using std::numeric_limits;

// Error conditions in the formatter are, in general, reported by
// emitting some sort of placeholder, surrounded by VT-220 reverse
// video escapes.  It is my understanding that these escapes work
// basically everywhere nowadays.

#define BEGIN_ERRMSG "\033[7m"
#define END_ERRMSG "\033[27m"

// The exposed interface guarantees not to throw exceptions under any
// circumstances, which means we have to intercept all exceptions and
// do something sensible.  "Sensible" in this case means: first try to
// insert some sort of placeholder in place of whatever we were
// formatting, and if that fails (perhaps due to OOM), crash.

static const char exception_msg[] = BEGIN_ERRMSG "[exception]" END_ERRMSG;

// This message appears when there were not enough arguments for the
// format string.

static const char not_enough_args[] = BEGIN_ERRMSG "[missing]" END_ERRMSG;

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
  memset(&spec, 0, sizeof(format_spec));
  spec.arg_index       = default_index;

  char *endp;
  if (*p >= '0' && *p <= '9') {
    spec.arg_index = strtoul(p, &endp, 10);
    if (endp == p) goto error; // this shouldn't happen, but we check anyway
    p = endp;
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
    spec.had_precision = true;
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
  memset(&spec, 0, sizeof(format_spec));
  while (*p != '\0' && *p != '}')
    p++;
  if (*p == '}')
    p++;
  return p;
}

//
// Per-actual-type formatting subroutines.
//

template <typename T>
static void
do_sprintf(T val, const format_spec &spec, char type, bool error, string &out)
{
  char format[11]; // "%#0-+ *.*llT";
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
      throw "format failure";
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format,
                   spec.width, spec.precision, val) != nreq) {
        delete [] s;
        throw "format failure";
      }
    }
  } else if (had_width) {
    int nreq = snprintf(buf1, sizeof buf1, format, spec.width, val);
    if (nreq < 0)
      throw "format failure";
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format, spec.width, val) != nreq) {
        delete [] s;
        throw "format failure";
      }
    }
  } else if (had_prec) {
    int nreq = snprintf(buf1, sizeof buf1, format, spec.precision, val);
    if (nreq < 0)
      throw "format failure";
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format, spec.precision, val) != nreq) {
        delete [] s;
        throw "format failure";
      }
    }
  } else {
    int nreq = snprintf(buf1, sizeof buf1, format, val);
    if (nreq < 0)
      throw "format failure";
    if (unsigned(nreq) >= sizeof buf1) {
      s = new char[nreq+1];
      if (snprintf(s, nreq+1, format, val) != nreq) {
        delete [] s;
        throw "format failure";
      }
    }
  }

  bool already_error = !out.empty();
  if (error && !already_error)
    out.append(BEGIN_ERRMSG);
  out.append(s);
  if (error && !already_error)
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
  if (type == 'd')
    type = 'u'; // not an error, but must mark unsignedness for sprintf
  else if (type == 'o' || type == 'x' || type == 'X')
    /* ok as is */;
  else {
    type = 'u';
    error = true;
  }
  do_sprintf(val, spec, type, error, out);
}

static void
do_format_signed_int(long long val,
                     const format_spec &spec,
                     string &out)
{
  char type = spec.type;
  bool error = false;
  if (type != 'd' && type != 'o' && type != 'x' && type != 'X') {
    type = 'd';
    error = true;
  }
  do_sprintf(val, spec, type, error, out);
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
    type = 'f';
    error = true;
  }
  do_sprintf(val, spec, type, error, out);
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
    if (!spec.flag_minus && spec.has_width && spec.width > 1)
      out.append(spec.width - 1, ' ');

    out.append(1, (unsigned char)val);

    if (spec.flag_minus && spec.has_width && spec.width > 1)
      out.append(spec.width - 1, ' ');

  } else {
    // reverse video if we aren't already, and bounce to format_unsigned_int.
    bool already_error = !out.empty();
    if (!already_error)
      out.append(BEGIN_ERRMSG);
    do_format_unsigned_int(val, spec, out);
    if (!already_error)
      out.append(END_ERRMSG);
  }
}

static void
do_format_str(const string &val,
              const format_spec &spec,
              string &out)
{
  bool already_error = false;
  if (spec.type != 's') {
    already_error = !out.empty();
    if (!already_error)
      out.append(BEGIN_ERRMSG);
  }

  // string truncated to precision, padded to width.
  // +, SPC, #, 0 modifiers ignored.

  size_t slen = val.size();
  if (spec.has_prec && spec.precision < slen)
    slen = spec.precision;

  size_t pad = 0;
  if (spec.has_width && spec.width > slen)
    pad = spec.width - slen;

  if (pad && !spec.flag_minus)
    out.append(pad, ' ');

  out.append(val, 0, slen);

  if (pad && spec.flag_minus)
    out.append(pad, ' ');

  if (spec.type != 's') {
    if (!already_error)
      out.append(END_ERRMSG);
  }
}

static void
do_format_cstr(const char *val,
               const format_spec &spec,
               string &out)
{
  bool already_error = false;
  if (spec.type != 's') {
    already_error = !out.empty();
    if (!already_error)
      out.append(BEGIN_ERRMSG);
  }

  // string truncated to precision, padded to width.
  // +, SPC, #, 0 modifiers ignored.
  // strnlen is not sufficiently portable to use here :(

  size_t slen;
  if (!spec.has_prec)
    slen = strlen(val);
  else
    for (const char *p = val; *p && slen < spec.precision; p++)
      slen++;

  size_t pad = 0;
  if (spec.has_width && spec.width > slen)
    pad = spec.width - slen;

  if (pad && !spec.flag_minus)
    out.append(pad, ' ');

  out.append(val, slen);

  if (pad && spec.flag_minus)
    out.append(pad, ' ');

  if (spec.type != 's') {
    if (!already_error)
      out.append(END_ERRMSG);
  }
}

namespace fmt {

void
formatter::format_sub(size_t, char) noexcept
{
}

void
formatter::format_sub(size_t, int) noexcept
{
}

void
formatter::format_sub(size_t, unsigned int) noexcept
{
}

void
formatter::format_sub(size_t, long long) noexcept
{
}

void
formatter::format_sub(size_t, unsigned long long) noexcept
{
}

void
formatter::format_sub(size_t, double) noexcept
{
}

void
formatter::format_sub(size_t, const char *) noexcept
{
}

void
formatter::format_sub(size_t, const void *) noexcept
{
}

void
formatter::format_sub(size_t, const std::string &) noexcept
{
}



} // namespace fmt

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End:
