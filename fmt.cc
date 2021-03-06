// c++fmt --- Self-contained string formatting library for C++
// Copyright 2012 Zachary Weinberg <zackw@panix.com>.  Use,
// modification, and distribution are subject to the Boost
// Software License, Version 1.0.  See the file LICENSE or
// http://www.boost.org/LICENSE_1_0.txt for detailed terms.

#include <cassert>  // must be first

#include <fmt.h>

#include <cerrno>
#include <cstdlib>  // free, strtoul
#include <cstring>  // strerror

#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>

// We assume <cxxabi.h> is available, and contains both
// abi::__cxa_current_exception_type and abi::__cxa_demangle, if the
// C++ runtime library declares itself as either libstdc++ or libc++.
#if __GLIBCXX__ >= 20011118 || _LIBCPP_VERSION >= 1001
  #define HAVE_CXA_EXCEPTION_INFO
  #include <typeinfo>
  #include <cxxabi.h>
#endif

using std::conditional;
using std::enable_if;
using std::exception;
using std::is_integral;
using std::is_same;
using std::is_signed;
using std::is_unsigned;
using std::make_unsigned;
using std::string;
using std::terminate;

namespace {

// We must avoid writing a direct cast from void * to an integer of a
// different size.  We don't know what size a pointer is, we cannot
// rely on the existence of stdint.h or uintptr_t, and we cannot rely
// on size_t being the same size as a pointer either (thanks ever so
// much, Microsoft).

typedef conditional<
  sizeof(void *) == sizeof(unsigned int), unsigned int,
  typename conditional<
    sizeof(void *) == sizeof(unsigned long), unsigned long,
    typename conditional<
      sizeof(void *) == sizeof(unsigned long long), unsigned long long,
      double // failure marker
    >::type
  >::type
>::type uintptrt;

static_assert(!is_same<uintptrt, double>::value,
              "failed to detect an integral type with the width of 'void *'");

// Similarly for 'double'.
typedef conditional<
  sizeof(double) == sizeof(unsigned int), unsigned int,
  typename conditional<
    sizeof(double) == sizeof(unsigned long), unsigned long,
    typename conditional<
      sizeof(double) == sizeof(unsigned long long), unsigned long long,
      double // failure marker
    >::type
  >::type
>::type uintdoublet;

static_assert(!is_same<uintdoublet, double>::value,
              "failed to detect an integral type with the width of 'double'");

// Ensure that we can print values of these types without casting.

static_assert(sizeof(size_t) <= sizeof(unsigned long long),
              "'unsigned long long' is not big enough for 'size_t'");
static_assert(sizeof(ptrdiff_t) <= sizeof(long long),
              "'long long' is not big enough for 'ptrdiff_t'");

// Determine whether a value of unspecified type, which may or may not
// be signed, is negative, without provoking "comparison is always
// true" warnings.

template <typename T>
bool
is_negative(T t, typename enable_if<is_signed<T>::value>::type* = 0)
{
  return t < 0;
}

template <typename T>
bool
is_negative(T, typename enable_if<is_unsigned<T>::value>::type* = 0)
{
  return false;
}

// make_unsigned causes a compile-time error if applied to a
// floating-point type. conditional does not (reliably) prevent
// this error.
template <typename T, typename = void>
struct unsigned_if_integral
{
  typedef T type;
};

template <typename T>
struct unsigned_if_integral<T, typename enable_if<is_integral<T>::value>::type>
{
  typedef typename make_unsigned<T>::type type;
};

} // anonymous namespace

namespace fmt {

// Error conditions in the formatter are, in general, reported by
// emitting some sort of placeholder, surrounded by VT-220 reverse
// video escapes.  It is my understanding that these escapes work
// basically everywhere nowadays.

#define BEGIN_ERRMSG "\033[7m"
#define END_ERRMSG "\033[27m"

// The exposed interface guarantees not to throw exceptions under any
// circumstances, which means we have to intercept all exceptions and
// do something sensible.  "Sensible" in this case means: first try to
// insert a diagnostic marker in place of whatever we were formatting,
// and if that fails (perhaps due to OOM), crash.
//
// To detect nested failures and crash, below, we explicitly code
// catch (...) { terminate() } even though 'noexcept' is currently
// defined to call terminate if an exception is about to escape, for
// defensiveness against future changes to this behavior (noexcept is
// considered not fully baked).
//
// This function handles figuring out what to print for an arbitrary
// exception.  The general approach is borrowed from boost::exception,
// with additional cleverness from Monotone.

template <size_t N>
inline bool triml(string& s, const char (&leader)[N])
{
  if (!s.compare(0, N-1, leader)) {
    s.erase(0, N-1);
    return true;
  } else {
    return false;
  }
}

static void
trim_typename(string& tname)
{
  // We might have a mangled name here, so make a crude attempt to
  // demangle it.  This only works for standard exception objects as
  // mangled by the current g++ ABI.
  if (triml(tname, "St") || triml(tname, "_ZSt") || triml(tname, "__ZSt")) {
    size_t n = 0;
    while (tname[n] >= '0' && tname[n] <= '9')
      n++;
    tname.erase(0, n-1);
  } else {
    triml(tname, "class ");
    triml(tname, "std::");
  }
}

string
formatter::diagnose_current_exception()
{
  string message(BEGIN_ERRMSG "[");
  string what;
  string type;

  // this looks silly but is the most portable way to determine
  // whether the current exception is in fact a std::exception object.
  try {
    throw;
  } catch (exception const& e) {
    // extract what() and the type of the exception, if we can
    what = e.what();
    const char *tname = typeid(e).name();
#ifdef HAVE_CXA_EXCEPTION_INFO
    char *dname = abi::__cxa_demangle(tname, 0, 0, 0);
    if (dname) {
      type = dname;
      std::free(dname);
    } else
#endif
      type = tname;
  } catch (char const* e) {
    // we don't know why someone chose to throw a C string, but at
    // least we can print it
    what = e;
    type = "text exception";
  } catch (...) {
    // well, hopefully at least we can extract the type
#ifdef HAVE_CXA_EXCEPTION_INFO
    const char *tname = abi::__cxa_current_exception_type()->name();
    char *dname = abi::__cxa_demangle(tname, 0, 0, 0);
    if (dname) {
      type = dname;
      std::free(dname);
    } else
      type = tname;
#endif
  }

  trim_typename(type);
  trim_typename(what);

  // special case some combinations that would produce unhelpful messages
  if (type.empty() && what.empty()) {
    type = "unidentifiable exception";
  } else if (what == type) {
    what.clear();
    if (type == "exception")
      type = "generic exception";
    else if (type == "bad_alloc")
      type = "out of memory";
  } else if (what.empty()) {
    what = type;
    type = "unusual exception type";
  }

  message += type;
  if (!type.empty() && !what.empty())
    message += ": ";
  message += what;
  message += "]" END_ERRMSG;

  return message;
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
  using std::strtoul;

  spec.arg_index = default_index;

  char *endp;
  if (*p >= '0' && *p <= '9') {
    spec.arg_index = strtoul(p, &endp, 10);
    assert(endp > p);
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
    assert(endp > p);
    p = endp;
  }

  if (*p == '.') {
    p++;
    spec.has_precision = true;
    spec.precision = strtoul(p, &endp, 10);
    if (endp == p) goto error; // no number present after '.'
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
  // find the next matching close brace or the end of the string
  unsigned int depth = 1;
  for (;;) {
    char c = *p;
    if (*p == '\0')
      break;
    p++;
    if (c == '{')
      depth++;
    if (c == '}') {
      depth--;
      if (depth == 0)
        break;
    }
  }
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
  std::vector<format_spec> extras; // Used only if there is more than one spec
                                   // referring to the same argument index.

  for (const char *p = str; *p; ) {
    if (*p == '{') {
      if (*(p+1) == '{') {
        cseg.append(1, *p);
        p += 2;
      } else {
        format_spec spec;
        const char *endp = parse_subst(p+1, default_index, spec);
        if (spec.arg_index == format_spec::i_invalid) {
          cseg.append(BEGIN_ERRMSG);
          cseg.append(p, endp - p);
          cseg.append(END_ERRMSG);
        } else if (spec.arg_index >= specs.size() &&
                   spec.arg_index != format_spec::i_errno) {
          // Spec requests conversion of an actual argument that isn't there.
          cseg.append(BEGIN_ERRMSG "[missing]" END_ERRMSG);
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
      align = (type == 's') ? '<' : '>';

    if (align == '<') {
      out.append(s);
      out.append(pad, spec.fill);

    } else if (align == '>') {
      out.append(pad, spec.fill);
      out.append(s);

    } else if (align == '^') {
      // If there are an odd number of padding characters required,
      // put one more on the right.
      out.append(pad/2, spec.fill);
      out.append(s);
      out.append(pad/2 + pad%2, spec.fill);

    } else {
      assert(align == '=');
      unsigned int leading = 0;
      if (type != 's' && type != 'c' && (s[0] == '-' || spec.sign != '-'))
        leading = 1;
      if (spec.alternate_form && (type == 'o' || type == 'x' || type == 'X'))
        leading += 2;

      out.append(s.substr(0, leading));
      out.append(pad, spec.fill);
      out.append(s.substr(leading));
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
  using std::ios;

  std::ostringstream os;
  os.exceptions(ios::failbit|ios::badbit|ios::eofbit);

  // iostreams can mark positive values with '+' but not with a space,
  // so we do it ourselves in both cases.
  // Python prints negative hex/oct numbers as a minus sign followed
  // by the absolute value, iostreams coerces to unsigned; I think the
  // Python behavior is more useful
  // to handle the most negative possible value of a twos-complement
  // signed integral type correctly, we need to assign to an unsigned
  // type after taking the absolute value, because of the asymmetric
  // range of such types.  this is not an issue for floating point.
  typename unsigned_if_integral<T>::type uval;
  if (is_negative(val)) {
    uval = -val;
    os << '-';
  } else {
    uval = val;
    if (spec.sign != '-')
      os << spec.sign;
  }

  // iostreams 'o' alternate form is '0nnnn' not '0onnnn'
  if (spec.alternate_form) {
    if (type == 'o')
      os << "0o";
    else if (type == 'x')
      os << "0x";
    else if (type == 'X')
      os << "0X";
  }

  if (spec.has_precision)
    os.precision(spec.precision);

  // Python doesn't allow # in floating point format specifications.
  // Its 'e' and 'f' typecodes always print floating point numbers
  // with a visible decimal point; 'g' doesn't.  Its behavior for
  // floating point numbers in the absence of a typecode is not the
  // same as 'e', 'f', or 'g', and has an asymmetry that makes it hard
  // to duplicate with iostreams, so we diverge and default to 'g'.
  if (type == 'e' || type == 'E') {
    os.setf(ios::scientific, ios::floatfield);
    os.setf(ios::showpoint);
  } else if (type == 'f' || type == 'F') {
    os.setf(ios::fixed, ios::floatfield);
    os.setf(ios::showpoint);
  }

  // decimal is the default
  if (type == 'o')
    os.setf(ios::oct, ios::basefield);
  else if (type == 'x' || type == 'X')
    os.setf(ios::hex, ios::basefield);

  if (type == 'E' || type == 'F' || type == 'G' || type == 'X')
    os.setf(ios::uppercase);

  os << uval;

  do_alignment(os.str(), spec, type, error, out);
}

static void
do_format_unsigned_int(unsigned long long val,
                       const format_spec &spec,
                       string &out)
{
  switch (spec.type) {
  case 'u':
  case 'd':
  case 'o':
  case 'x':
  case 'X':
    do_numeric_format(val, spec, spec.type, false, out);
    return;

  case 'e': case 'E':
  case 'f': case 'F':
  case 'g': case 'G':
    do_numeric_format(double(val), spec, spec.type, false, out);
    return;

  default:
    do_numeric_format(val, spec, 'u', true, out);
    return;
  }
}

static void
do_format_signed_int(long long val,
                     const format_spec &spec,
                     string &out)
{
  switch (spec.type) {
  case 'u':
  case 'd':
  case 'o':
  case 'x':
  case 'X':
    do_numeric_format(val, spec, spec.type, false, out);
    return;

  case 'e': case 'E':
  case 'f': case 'F':
  case 'g': case 'G':
    do_numeric_format(double(val), spec, spec.type, false, out);
    return;

  default:
    do_numeric_format(val, spec, 'd', true, out);
    return;
  }
}

static void
do_format_float(double val,
                const format_spec &spec,
                string &out)
{
  switch (spec.type) {
  case 'e': case 'E':
  case 'f': case 'F':
  case 'g': case 'G':
    do_numeric_format(val, spec, spec.type, false, out);
    return;

  case 'u':
  case 'd':
  case 'o':
  case 'x':
  case 'X': {
    union {
      double d;
      uintdoublet i;
    } u;
    u.d = val;
    // Cast to 'unsigned long long' after extraction, so the compiler
    // won't instantiate another version of do_numeric_format
    // if uintdoublet is a different type.
    do_numeric_format((unsigned long long)(u.i), spec, spec.type, false, out);
  } return;

  default:
    do_numeric_format(val, spec, 'g', true, out);
    return;
  }
}

// This takes unsigned long long instead of the actual character so it
// can do something sensible on overflow.
static void
do_format_char(unsigned long long val,
               const format_spec &spec,
               string &out)
{
  if ((spec.type == 'c' || spec.type == 's')
      && val <= std::numeric_limits<unsigned char>::max()) {
    // Most modifiers are ignored; just emit the character with
    // appropriate padding.  If the precision is zero, print the
    // empty string.
    if (spec.has_precision && spec.precision == 0)
      do_alignment(string(), spec, spec.type, false, out);
    else
      do_alignment(string(1, val), spec, spec.type, false, out);
  } else
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 's';

      switch (spec->type) {
      case 'c':
      case 's':
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
    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 'd';

      switch (spec->type) {
      case 'c':
        do_format_char(val, *spec, segs.at(spec->target));
        break;

      case 'd':
      case 'u':
      case 'o':
      case 'x':
      case 'X':
      default:
        do_format_signed_int(val, *spec, segs.at(spec->target));
        break;
      }
    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 'u';

      switch (spec->type) {
      case 'c':
        do_format_char(val, *spec, segs.at(spec->target));
        break;

      case 'd':
      case 'u':
      case 'o':
      case 'x':
      case 'X':
      default:
        do_format_unsigned_int(val, *spec, segs.at(spec->target));
        break;
      }
    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 'x';
      if (!spec->has_width) {
        spec->has_width = true;
        spec->width = sizeof(void *) * 2;
        spec->fill = '0';
        spec->align = '>';
      }
      do_format_unsigned_int(uintptrt(val), *spec,
                             segs.at(spec->target));
    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 'g';
      do_format_float(val, *spec, segs.at(spec->target));
    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 's';
      do_format_cstr(val, *spec, segs.at(spec->target));
    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
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
  assert(spec->arg_index == i);
  for (;;) {
    try {
      if (spec->type == '\0')
        spec->type = 's';
      do_format_str(val, *spec, segs.at(spec->target));

    } catch (...) {
      try {
        segs.at(spec->target) = diagnose_current_exception();
      } catch (...) {
        terminate();
      }
    }

    i = spec->next_this_index;
    if (i == format_spec::i_invalid)
      break;
    spec = &specs[i];
  }
}

void
formatter::format_exc(size_t i) noexcept
{
  try {
    format_sub(i, diagnose_current_exception());
  } catch (...) {
    terminate();
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
      format_sub(format_spec::i_errno, std::strerror(saved_errno));
    }

  } catch (...) {
    try {
      nargs = 0;
      first_errno_spec.reset();
      specs.clear();
      segs.resize(1);
      segs[0] = diagnose_current_exception();
    } catch (...) {
      terminate();
    }
  }
}

string
formatter::finish() noexcept
{
  try {
    return std::accumulate(segs.begin(), segs.end(), string(""));

  } catch (...) {
    try {
      return diagnose_current_exception();
    } catch (...) {
      terminate();
    }
  }
}

} // namespace fmt

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End:
