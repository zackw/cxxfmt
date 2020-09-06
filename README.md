# c++fmt --- Self-contained string formatting library for C++

This is another string formatting library for C++.  It is inspired by
[Boost.Format][], Python 3’s [new string formatting][p3fmt], and
[FastFormat][].  You might prefer it to the above, or to the stock
facilities of the language, because it’s:

* _Self-contained:_ One header file and one source file, requiring no
  special configuration or external dependencies, designed to be
  copied into your project.
* _Typesafe:_ Cannot be tricked into interpreting integers as
  pointers, or anything like that; can figure out how big all your
  data is for itself.
* _Succinct_: What you write in your source code is similar to
  what you would write if you were using good old `printf`.
* _Comprehensive:_ Provides nearly all the facilities of Python
  3’s very capable string formatting (see below for exceptions).

I don’t have a use for this library anymore, so I’m not planning to
do any further work on it myself.  I hope it is useful to you
as-is.  I will consider bug reports and patches, particularly as
suggested below, but my time for hacking on random old projects is
limited so please be patient.

## Dependencies

This library depends on a number of C++2011 language and library
features, most notably [variadic templates][].  It is known to work
with:

 * GCC 4.7 or later, in `-std=c++11` mode.
 * Clang++ 3.0 or later, in `-std=c++11` mode, using either GCC
   4.7-or-later’s `libstdc++`, or `libc++`.  I don’t know how new you
   need `libc++` to be.

It is known *not* to work with:

 * GCC 4.6 or earlier, even in `-std=c++0x` mode, due to the absence
   of [`std::underlying_type`][typetraits].  This will also affect any
   other compiler that reuses GCC 4.6’s `libstdc++`.

The test suite requires Python 3.  It will identify all usable
compilers that it knows how to drive, which is currently limited
to GCC and Clang on Unixy systems.

Patches to support additional compilers and operating systems are
welcome.  I’ll consider anything, but I’m more inclined to kludge
around incomplete or broken functionality if it’s provided by the
OS than the compiler.

## Usage

```c++
#include <iostream>
#include <fmt.h>

std::cout << fmt::format("I have {} teapots\n", 23);
```

The `format` function returns a `std::string`.  The
[syntax of format strings][p3fmt] is copied from Python 3, with the
following lacunae:

1. Nested replacement fields are not supported.
2. The `'b'`, `'n'`, and `'%'` presentation types are not supported.
3. Named replacement fields are not supported, nor are attribute or
   index extractions.  However, as a special case, writing `{m}` or
   `{m:spec}` will cause the library to substitute `strerror(errno)`
   at that point.
4. Pre-format conversions (`!r`, `!s`, etc) are not supported.

and deliberate divergences:

1. `{}` is the same as `{:g}` for floating point types.  Python’s
   behavior in the absence of a typecode does not exactly correspond
   to `'e'`, `'f'`, or `'g'` and is impractical to emulate.
2. You may not combine the `'0'` modifier with an explicit alignment
   specification.  Python allows this but its behavior is internally
   inconsistent.

Ill-formed format specifications are printed as literal text, but
surrounded by VT-220 reverse video escapes.

All built-in types may be passed as extended arguments to `fmt`, as
may `std::string` and any type that exposes any of the following:

* A conversion operator to either `std::string` or `const char *`.
* A method with any of these signatures:
  * `std::string str() const`
  * `const char *str() const`
  * `const char *c_str() const`
  * `const char *what() const` (this last allows passing
    `std::exception` objects directly to a format call).

## Exceptions

`fmt::format` guarantees not to throw exceptions from its internals
under any circumstances whatsoever, and to intercept exceptions thrown
by conversion functions from the list above.  However, it cannot
intercept exceptions thrown by explicitly-written function calls or
other complex expressions within its argument list.

If `format` traps an exception or encounters an internal failure, it
will insert a human-readable placeholder, surrounded by VT-220 reverse
video escapes, in place of either the substitution that failed, or the
entire string.  If even that can’t be made to work (for instance, if
memory allocation fails during construction of the placeholder
string), `format` will call `std::terminate`.

## Parameter Mismatch Handling

Mismatches between the format string and the substitution arguments
are currently not detected at compile time, since we would have to
inspect the contents of the format string to do so.  However, the
library guarantees to detect and safely handle mismatches at runtime,
as follows:

* If there are more arguments than required by the format string, the
  excess arguments are ignored.  Note that all arguments will still be
  fully evaluated and converted to strings.

* If there are fewer arguments than required, the substitution markers
  that don’t correspond to arguments will produce the placeholder
  string `[missing]`, surrounded by VT-220 reverse video escapes.

* If you don’t specify a type code, it will be derived from the actual
  type of the datum.  Doing this is encouraged whenever you don’t need
  to request a particular integer or floating-point “presentation.”

* `printf`-style size modifiers to the type code are unnecessary
  (and treated as ill-formed format specs).

* Applying a floating-point type code to an integer will implicitly
  convert the integer to an appropriately-sized floating-point number.

* Applying an integer type code to a floating-point number or a bare
  pointer will print the integer corresponding to its bit
  representation.

* Any other mismatch will cause the mismatched datum to be printed as
  if there had been no type code, but surrounded by VT-220 reverse
  video escapes.

## Future directions

I would review and merge patches to do any of the following:

* Parse format strings at compile time, somehow ([`operator""`][udl]?)
  and validate them against the variadic argument list.

* Implement runtime-variable width and precision, the remaining
  presentation types, or any other feature of Python’s format strings
  that isn’t already supported (see the list of “lacunae” above).

* Add support for UTF-8 strings (`u8"..."`) in format strings and
  arguments.

* Add support for arbitrary UTF-8 composed glyphs as fill characters.

* Add support for formatting objects that provide an iostream
  `operator<<`.

* Add a more flexible user-defined conversion method, probably with
  the signature

        std::string format(const fmt::format_spec &) const

[udl]: https://en.cppreference.com/w/cpp/language/user_literal

## Future non-directions

Since the existing code depends heavily on variadic templates, a port
to C++1998 would be so different that it should be maintained as a
separate project.

I am not interested in patches adding support for classic “wide” strings.
As far as I’m concerned, these are not fit for *any* purpose and should
be removed from the C++ standard.

I could possibly be persuaded to merge patches adding support for
UTF-16 or UTF-32 strings, but I would need to see a compelling
argument why it’s not enough to format into a UTF-8 string and then
use `std::codecvt` to convert the result to UTF-16 or UTF-32.

[Boost.Format]: http://www.boost.org/doc/libs/1_51_0/libs/format/doc/format.html
[p3fmt]: http://docs.python.org/py3k/library/string.html#format-string-syntax
[FastFormat]: http://fastformat.org/
[variadic templates]: https://en.wikipedia.org/wiki/Variadic_template#C.2B.2B11
[typetraits]: http://www.cplusplus.com/reference/std/type_traits/
