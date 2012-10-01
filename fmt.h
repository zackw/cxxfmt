// c++fmt --- Self-contained string formatting library for C++
// Copyright 2012 Zachary Weinberg <zackw@panix.com>.  Use,
// modification, and distribution are subject to the Boost
// Software License, Version 1.0.  See the file LICENSE or
// http://www.boost.org/LICENSE_1_0.txt for detailed terms.

#ifndef CXXFMT_FMT_H__
#define CXXFMT_FMT_H__

#include <stddef.h>

#include <type_traits>
#include <string>
#include <vector>

namespace fmt {

namespace detail {

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
CXXFMT_HAS_MEM_FUNC(what);

#undef CXXFMT_HAS_MEM_FUNC

} // namespace detail

//
// The next two classes may someday be part of the public API, but
// right now, use at your own risk.
//

struct format_spec
{
  size_t arg_index;       // 1-based argument index
  size_t next_this_index; // 1-based index in the 'specs' array of the
                          // next spec that uses the same argument index,
                          // if any; 0 otherwise.

  unsigned int width;
  unsigned int precision;
  char type;
  bool had_width  : 1;
  bool had_prec   : 1;
  bool flag_hash  : 1;
  bool flag_zero  : 1;
  bool flag_minus : 1;
  bool flag_plus  : 1;
  bool flag_space : 1;
};

class formatter
{
  size_t nargs;
  std::vector<std::string> segments;
  std::vector<format_spec> specs;

  // Base format categories.  These methods do the actual work of
  // rendering each substitution.
  void format_sub(size_t, unsigned char) noexcept;
  void format_sub(size_t, long long) noexcept;
  void format_sub(size_t, unsigned long long) noexcept;
  void format_sub(size_t, double) noexcept;
  void format_sub(size_t, const char *) noexcept;
  void format_sub(size_t, const void *) noexcept;
  void format_sub(size_t, const std::string &) noexcept;

  // Adapters pick the appropriate base category for every possible
  // argument.

  // Convert 'signed char' and 'char' to 'unsigned char'.
  void format_sub(size_t n, signed char t)
  { format_sub(n, (unsigned char)(t)); }
  void format_sub(size_t n, char t)
  { format_sub(n, (unsigned char)(t)); }

  // Convert 'float' to 'double'.
  void format_sub(size_t n, float t)
  { format_sub(n, (double)(t)); }

  // Convert all integral, non-char types to 'long long' with the same
  // signedness.  Note that if 'long' and/or 'int' are the same size
  // as 'long long' they still need explicit mapping, but we have to
  // be careful not to have the adapter templates conflict with the
  // base case above.
  template <typename T>
  void format_sub(size_t n, T t,
                  typename std::enable_if<
                    (std::is_integral<T>::value
                     && std::is_unsigned<T>::value
                     && !std::is_same<T, unsigned long long>::value
                     && sizeof(T) > 1
                     && sizeof(T) <= sizeof(unsigned long long))
                  >::type* = 0)
  { format_sub(n, (unsigned long long)(t)); }

  template <typename T>
  void format_sub(size_t n, T t,
                  typename std::enable_if<
                    (std::is_integral<T>::value
                     && std::is_signed<T>::value
                     && !std::is_same<T, long long>::value
                     && sizeof(T) > 1
                     && sizeof(T) <= sizeof(long long))
                  >::type* = 0)
  { format_sub(n, (long long)(t)); }

  // Convert enums to their underlying integral type.
  template <typename T>
  void format_sub(size_t n, T t,
                  typename std::enable_if<
                    std::is_enum<T>::value
                  >::type* = 0)
  { format_sub(n, (typename std::underlying_type<T>::type)(t)); }

  // Convert any object that can be converted to a string, either by
  // construction or by member methods.
  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<
                    std::is_constructible<std::string, T>::value
                  >::type* = 0)
  { format_sub(n, std::string(t)); }

  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<
                    (detail::has_str<T, const char *(T::*)() const>::value ||
                     detail::has_str<T, std::string (T::*)() const>::value ||
                     detail::has_str<T,const std::string&(T::*)()const>::value)
                  >::type* = 0)
  { format_sub(n, t.str()); }

  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<
                    detail::has_c_str<T, const char *(T::*)() const>::value
                  >::type* = 0)
  { format_sub(n, t.c_str()); }

  template <typename T>
  void format_sub(size_t n, const T& t,
                  typename std::enable_if<
                    detail::has_what<T, const char *(T::*)() const>::value
                  >::type* = 0)
  { format_sub(n, t.what()); }

  // Convert arbitrary pointers to 'void *'.
  template <typename T>
  void format_sub(size_t n, const T* t)
  { format_sub(n, reinterpret_cast<const void *>(t)); }

public:
  formatter(size_t nargs, const char *msg) noexcept;
  ~formatter() noexcept;

  std::string finish() noexcept;

  // Recursive template to prepare a whole argpack of substitutions.
  void format_subs(size_t) {}

  template <typename X, typename... XS> void
  format_subs(size_t n, X&& x, XS&&... xs)
  {
    format_sub(n, x);
    format_subs(n+1, xs...);
  }
};

//
// This is the exposed interface.
//

template <typename... XS> inline std::string
format(const char *msg, XS&&... xs)
{
  size_t nargs = sizeof...(xs);
  formatter state(nargs, msg);
  state.format_subs(0, xs...);
  return state.finish();
}

} // namespace fmt

#endif // fmt.h

// Local Variables:
// mode: c++
// c-file-offsets: ((innamespace . 0))
// End:
