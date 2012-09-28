// c++fmt --- Self-contained string formatting library for C++
// Copyright 2012 Zachary Weinberg <zackw@panix.com>.  Use,
// modification, and distribution are subject to the Boost
// Software License, Version 1.0.  See the file LICENSE or
// http://www.boost.org/LICENSE_1_0.txt for detailed terms.

#ifndef CXXFMT_FMT_H__
#define CXXFMT_FMT_H__

#include <string>
#include <type_traits>
#include <limits.h>
#include <stddef.h>

namespace fmt {

namespace detail {

// Find a 64-bit integer type.
#if ULONG_MAX >= 18446744073709551615UL
  typedef long int64;
  typedef unsigned long uint64;
#elif defined ULLONG_MAX && ULLONG_MAX >= 18446744073709551615UL
  typedef long long int64;
  typedef unsigned long long uint64;
#elif defined _UI64_MAX && _UI64_MAX >= 18446744073709551615UL
  typedef __int64 int64;
  typedef unsigned __int64 uint64;
#else
  #error "Failed to find a 64-bit integer type."
#endif

static_assert(sizeof(int64) >= sizeof(ptrdiff_t),
              "ptrdiff_t is too large for int64");
static_assert(sizeof(uint64) >= sizeof(size_t),
              "size_t is too large for uint64");

union datum
{
  const void* vp;
  const char* cs;
  const std::string* xs;
  int64 si;
  uint64 ui;
  double fp;
};

struct format_data
{
  char*  types;
  datum* data;
  size_t n;

  format_data(char* t, datum* d, size_t n) : types(t), data(d), n(n) {}

  std::string format() const;
};

//
// Work out what should be done with one argument to the formatter.
//

#define PROCESS_ARG_CVT(CODE, SLOT, TYPE, CONV)         \
  inline void                                           \
  process_arg(format_data& f, size_t n, TYPE t)         \
  {                                                     \
    f.types[n] = CODE;                                  \
    f.data[n].SLOT = CONV(t);                           \
  }

#define PROCESS_ARG_CND(CODE, SLOT, COND, CONV)         \
  template <typename T,                                 \
            typename = std::enable_if<COND>::type>      \
  PROCESS_ARG_CVT(CODE, SLOT, T, CONV)

#define PROCESS_ARG(CODE, SLOT, TYPE)                   \
  PROCESS_ARG_CVT(CODE, SLOT, TYPE, /**/)

#define PROCESS_ARG_INT(CODE, TYPE)                     \
  PROCESS_ARG(CODE, si, signed TYPE)                    \
  PROCESS_ARG(CODE, ui, unsigned TYPE)

PROCESS_ARG_INT('c', char)
PROCESS_ARG_INT('i', short)
PROCESS_ARG_INT('i', int)
PROCESS_ARG_INT('i', long)
#if defined ULLONG_MAX && ULLONG_MAX > ULONG_MAX
PROCESS_ARG_INT('i', long long)
#elif defined _UI64_MAX && _UI64_MAX > ULONG_MAX
PROCESS_ARG_INT('i', __int64)
#endif

PROCESS_ARG('f', fp, float)
PROCESS_ARG('f', fp, double)
PROCESS_ARG('p', vp, const void *)

// Strings and things which are convertible to strings

PROCESS_ARG('s', cs, const char *)
PROCESS_ARG_CVT('S', xs, const ::std::string &&, &)

#if 0
PROCESS_ARG_CND('s', cs,
                (std::is_constructible<const char *, T>::value),
                (const char *))

PROCESS_ARG_CND('S', xs,
                (std::is_constructible<std::string, T>::value),
                & std::string)

// Explicit to-string methods

#define HAS_MEM_FUNC(func)                                              \
  template<typename T, typename Sign>                                   \
  struct has_##func {                                                   \
    typedef char yes[1];                                                \
    typedef char no [2];                                                \
    template <typename U, U> struct type_check;                         \
    template <typename _1> static yes &chk(type_check<Sign, &_1::func> *); \
    template <typename   > static no  &chk(...);                        \
    static bool const value = sizeof(chk<T>(0)) == sizeof(yes);         \
  }

HAS_MEM_FUNC(str);
HAS_MEM_FUNC(c_str);

#undef HAS_MEM_FUNC

#define INVOKE_STR(x)   ((x).str())
#define INVOKE_C_STR(x) ((x).c_str())

PROCESS_ARG_CND('s', cs,
                (has_c_str<T, const char * (T::*)() const>),
                INVOKE_C_STR)
PROCESS_ARG_CND('s', cs,
                (has_str<T, const char * (T::*)() const>),
                INVOKE_STR)
PROCESS_ARG_CND('S', xs,
                (has_str<T, std::string (T::*)() const>),
                & INVOKE_STR)

#undef INVOKE_STR
#undef INVOKE_C_STR
#endif

#undef PROCESS_ARG_INT
#undef PROCESS_ARG
#undef PROCESS_ARG_CVT
#undef PROCESS_ARG_CND

//
// Recursive template processes each arg in turn.
//

inline void
process_args(format_data&, ::size_t)
{
}

template <typename X, typename... XS> inline void
process_args(format_data& f, ::size_t n, X&& x, XS&&... xs)
{
  process_arg(f, n, x);
  process_args(f, n+1, xs...);
}


} // namespace fmt::detail

//
// This is the exposed interface.
//

template <typename... XS> inline std::string
format(const char *msg, XS&&... xs)
{
  char  types[sizeof...(xs)];
  detail::datum data[sizeof...(xs)];
  detail::format_data fd(types, data, sizeof...(xs));

  detail::process_args(fd, 0, xs...);
  return fd.format();
}

} // namespace fmt

#endif // fmt.h

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End:
