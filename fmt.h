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

// Detection of class methods.
#define CXXFMT_HAS_MEM_FUNC(func)                                       \
  template<typename T, typename Sign>                                   \
  struct has_##func {                                                   \
    typedef char yes[1];                                                \
    typedef char no [2];                                                \
    template <typename U, U> struct type_check;                         \
    template <typename _1> static yes &chk(type_check<Sign, &_1::func> *); \
    template <typename   > static no  &chk(...);                        \
    static bool const value = sizeof(chk<T>(0)) == sizeof(yes);         \
  }

CXXFMT_HAS_MEM_FUNC(str);
CXXFMT_HAS_MEM_FUNC(c_str);

#undef CXXFMT_HAS_MEM_FUNC

class Formatter
{
  size_t nargs;
  const char *msg;
  std::string *specs;
  std::string *subs;

public:
  Formatter(size_t nargs,
            const char *msg,
            std::string *specs,
            std::string *subs);
  ~Formatter() {}

  std::string finish();

  // Recursive template to prepare a whole argpack of substitutions.
  void format_subs(size_t) {}

  template <typename X, typename... XS> void
  format_subs(size_t n, X&& x, XS&&... xs)
  {
    format_sub(n, x);
    format_subs(n+1, xs...);
  }

  // Base format categories.  These methods do the actual work of
  // rendering each substitution.
  void format_sub(size_t, char);
  void format_sub(size_t, uint64);
  void format_sub(size_t, int64);
  void format_sub(size_t, double);
  void format_sub(size_t, const char *);
  void format_sub(size_t, const void *);
  void format_sub(size_t, const std::string &);

  // Adapter templates pick the appropriate base category for every
  // possible argument.

  // Unsigned integral, not a char, smaller than 'uint64'.
  template <typename T>
  void format_sub(size_t n, T t,
                  typename std::enable_if<
                    (std::is_unsigned<T>::value
                     && !std::is_same<T, unsigned char>::value
                     && sizeof(T) < sizeof(uint64))>::type* = 0)
  { format_sub(n, uint64(t)); }

  // Signed integral, not a char, smaller than 'int64'.
  template <typename T>
  void format_sub(size_t n, T t,
                  typename std::enable_if<
                    (std::is_signed<T>::value
                     && !std::is_floating_point<T>::value
                     && !std::is_same<T, signed char>::value
                     && sizeof(T) < sizeof(int64))>::type* = 0)
  { format_sub(n, int64(t)); }

  // Floating point.  We only go up to 'double', which makes this
  // perhaps a little *too* generic, but what the heck.
  template <typename T>
  void format_sub(size_t n, T t,
                  typename std::enable_if<
                    (std::is_floating_point<T>::value
                     && sizeof(T) < sizeof(double))>::type* = 0)
  { format_sub(n, double(t)); }

  // Things which are convertible to strings, either by construction
  // or by member methods.
  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<
                    std::is_constructible<std::string, T>::value
                  >::type* = 0)
  { format_sub(n, std::string(t)); }

  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<(
                    has_str<T, const char *(T::*)() const>::value ||
                    has_str<T, std::string (T::*)() const>::value ||
                    has_str<T,const std::string&(T::*)()const>::value
                  )>::type* = 0)
  { format_sub(n, t.str()); }

  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<(
                    has_c_str<T, const char *(T::*)() const>::value ||
                    has_c_str<T, std::string (T::*)() const>::value ||
                    has_c_str<T,const std::string&(T::*)()const>::value
                  )>::type* = 0)
  { format_sub(n, t.c_str()); }
};


} // namespace fmt::detail

//
// This is the exposed interface.
//

template <typename... XS> inline std::string
format(const char *msg, XS&&... xs)
{
  size_t nargs = sizeof...(xs);
  std::string specs[nargs];
  std::string subs[nargs];
  detail::Formatter state(nargs, msg, specs, subs);
  state.format_subs(0, xs...);
  return state.finish();
}

} // namespace fmt

#endif // fmt.h

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End:
