# c++fmt --- Self-contained string formatting library for C++

This is another string formatting library for C++.  It is inspired by
[Boost.Format][], Python 3's [new string formatting][p3fmt], and
[FastFormat][].  You might prefer it to the above, or to the stock
facilities of the language, because it's:

* _Self-contained:_ One header file and one source file, requiring no
  special configuration or external dependencies, designed to be
  copied into your project.
* _Typesafe:_ Cannot be tricked into interpreting integers as
  pointers, or similar.
* _Succinct_: What you write in your source code is similar to
  what you would write if you were using good old `printf`.
* _Comprehensive:_ Anything you can do with `printf`, you can do with
  this. (A long-term goal is to provide all the facilities of Python
  3's string formatting, but we're not there yet.)

## Dependencies

This library depends on four C++2011 features: [variadic templates][],
[rvalue references][], [`<type_traits>`][typetraits], and
[`static_assert`][sassert].  You also need a `sprintf` that knows how
to print 64-bit integers (we detect C99 compliance and Windows), and
C++98 `<string>`.

If you want to run the test suite, you need Python 2.7 and either GCC
or Clang.  (Patches to teach the test suite how to invoke MSVC++ are
welcome.)

## Usage

    #include <fmt.h>
    #include <iostream>

    std::cout << fmt::format("I have {} teapots\n", 23);

The `format` function returns a `std::string`.  The
[syntax of format strings][p3fmt] is copied precisely from Python 3,
with the following lacunae:

1. Everything after a colon is currently passed verbatim to `sprintf`
   (except that the type code is validated, and if a `*` appears it is
   an error).  Consequently, expect `sprintf` behavior rather than
   Pythonic behavior where the two diverge.
2. Nested replacement fields are not supported.
3. Named replacement fields are not supported, nor are attribute or
   index extractions.
4. The `!r`, `!s`, and `!a` modifiers are not supported.

All built-in types may be passed as extended arguments to `fmt`, as
may `std::string` and any type that exposes any of the following:

* A conversion operator to either `std::string` or `const char *`.
* A method with any of these signatures:
  * `std::string str() const`
  * `const char *str() const`
  * `const char *c_str() const`

## Type Mismatch Handling

It is unfortunately not possible to make type mismatch a compile-time
error, since it depends on the contents of the format string.
However, the library guarantees to detect and safely handle type
mismatch at runtime, as follows:

* If you don't specify a type code, it will be derived from the actual
  type of the datum.  Doing this is encouraged whenever you don't need
  to request a particular integer or floating-point "presentation."

* Size modifiers to the type code are ignored in all cases.

* Applying a floating-point type code to an integer will implicitly
  convert the integer to an appropriately-sized floating-point number.

* Applying an integer type code to a floating-point number or a bare
  pointer will print the integer corresponding to its bit
  representation.

* Any other mismatch will cause the type code to be ignored, but the
  library will emit VT-100 reverse video escape sequences around the
  mismatched datum, so you notice the problem.

## Future directions

I plan to fix lacunae 1 and 2 in the format-string syntax (see above
under "Usage") as soon as possible.

I plan to offer a more flexible user-defined conversion method,
probably with the signature

    std::string format(const fmt::format_spec &) const

as soon as I actually need it myself, or if there is user demand.

I plan to add support for C++2011 UTF-8 strings eventually.

## Future non-directions

I do not intend to fix lacunae 3 and 4, unless someone suggests a
sensible and straightforward interpretation for them in a C++ context.

I do not intend to offer support for classic "wide" strings, or for
user-defined `operator<<`.  I might reconsider this if there is
demand, but I consider both very poorly designed and do not wish to
encourage their use.

[Boost.Format]: http://www.boost.org/doc/libs/1_51_0/libs/format/doc/format.html
[p3fmt]: http://docs.python.org/py3k/library/string.html#format-string-syntax
[FastFormat]: http://fastformat.org/
[variadic templates]: https://en.wikipedia.org/wiki/Variadic_template#C.2B.2B11
[rvalue references]:
[typetraits]: http://www.cplusplus.com/reference/std/type_traits/
[sassert]: 
