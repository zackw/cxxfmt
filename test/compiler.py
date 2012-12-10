
import collections
import glob
import json
import os
import os.path
import subprocess
import sys

import util

#
# Compiler detection and invocation
#

class Compiler(object):
    """Abstract base class for compilers installed on this computer.
       Instances provide an API for invoking their particular
       compiler.  The class itself provides an API for detecting
       installed compilers and determining their characteristics."""

    @util.lazy_property
    def DEVNULL(_):
        """Read-write file handle on /dev/null.  If possible,
           delegates to subprocess; otherwise opens a global handle on
           os.devnull itself.  If possible, that handle is marked
           close-on-exec.

           N.B. this is not in 'util' because descriptors do not apply
           to lookups in module objects, and thus @lazy_property does
           not work in that context."""
        try:
            return subprocess.DEVNULL
        except AttributeError:
            try:
                return os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
            except AttributeError:
                return os.open(os.devnull, os.O_RDWR)

    @staticmethod
    def identify(prog, extra_args=[]):
        """Find out which version of which compiler 'prog' is, and which
           C++ runtime library it offers, when invoked with 'extra_args'.
           'prog' should be an absolute pathname to an executable."""

        identify_source = """\
// We have to include some C++ library header to get the library's
// identifying macros defined.  There are no C++ library headers that
// define nothing but macros, so we put a marker after the #include
// ('%%', which is not syntactically valid C++ and therefore will not
// appear in the expansion of the #include) and strip out everything
// before that marker from Python.  This also gives us an opportunity
// to strip line markers and any other junk that may appear in
// preprocessor output.  If the compiler is already in C++11 mode,
// we include <type_traits> instead of <iosfwd> to detect more possible
// incompatibilities between the compiler and the library.

#if __cplusplus >= 201103L
#include <type_traits>
#else
#include <iosfwd>
#endif

%%

{
#if __cplusplus >= 201103L
  "cxx11" : 1,
#else
  "cxx11" : 0,
#endif
// clang defines __GNUC__ and might plausibly decide to define
// _MSC_VER on Windows, so check for it first.
#if defined __clang__
  "cc"    : "clang",
  "ccmaj" : __clang_major__,
  "ccmin" : __clang_minor__,
#elif defined __GNUC__
  "cc"    : "gcc",
  "ccmaj" : __GNUC__,
  "ccmin" : __GNUC_MINOR__,
#elif defined _MSC_VER
  "cc"    : "msvc",
  "ccmaj" : _MSC_VER,
  "ccmin" : 0,
#else
  "cc"    : "unknown",
  "ccmaj" : 0,
  "ccmin" : 0,
#endif
#if defined _LIBCPP_VERSION
  "lib"   : "llvm" // "libc++" is too generic
#elif defined __GLIBCXX__
  "lib"   : "gnu"
#elif defined _MSC_VER
  "lib"   : "ms"
#else
  "lib"   : "unknown"
#endif
}
"""

        try:
            # This is how g++ and clang++ want to be invoked.
            argv = [prog, "-E", "-xc++"] + extra_args + ["-"]
            #sys.stderr.write(" ".join(argv) + "\n")
            output = util.check_io(argv,
                                   stderr=Compiler.DEVNULL,
                                   input=identify_source)
        except subprocess.CalledProcessError:
            # Retry with appropriate switches for MSVC should go here.
            # I am getting a headache just looking at its documentation,
            # so it can wait.
            return { "cxx11" : 0,
                     "cc"    : "unknown",
                     "ccmaj" : 0,
                     "ccmin" : 0,
                     "lib"   : "unknown" }

        data = "".join(l for l in output[output.rfind("%%")+2:].splitlines()
                       if len(l) > 0 and l[0] != '#')
        props = json.loads(data)

        props["ccver"] = str(props["ccmaj"]) + "." + str(props["ccmin"])

        otag = ("-" + props["cc"] +
                "-" + props["ccver"] +
                "-lib" + props["lib"])
        if os.name == "nt" or os.name == "ce":
            otag += ".obj"
        else:
            otag += ".o"

        props["otag"] = otag
        return props

    def __init__(self, prog, props, flags, libs):
        """Constructor for Compiler (subclass) instances.  'prog' is
           the name of the compiler executable.  'props' MUST be the
           property dictionary returned by Compiler.identify(prog).
           'flags' is a list of command line switches to pass on all
           invocations of the compiler; 'libs' is an additional list
           of command line switches to pass when linking."""
        self.prog = prog
        self.props = props
        self.flags = flags
        self.libs = libs

    def objname(self, src):
        """Return an appropriately labeled name for an object file
           compiled from source file 'src' with this compiler."""
        return os.path.splitext(src)[0] + self.props["otag"]

    def invoke(self, args, label, verbose):
        """Invoke this compiler, passing 'args' on the command line.
           'verbose' says how much to report about this invocation.
           It takes one of the following numeric values:
              0: total silence.
              1: report success or failure.
              2: print full command line and error messages.
           'label' is used when verbose=1 to describe this invocation.
           Returns True for a successful compilation, False otherwise.
        """
        if verbose < 0 or verbose > 2:
            raise ValueError("bad verbosity {}".format(verbose))

        argv = [self.prog] + self.flags + args
        if verbose == 2:
            sys.stderr.write(" ".join(argv) + "\n")
            rv = subprocess.call(argv, stdin=Compiler.DEVNULL)
        else:
            if verbose == 1:
                sys.stderr.write("{} {}...".format(argv[0], label))
            rv = subprocess.call(argv,
                                 stdin=Compiler.DEVNULL,
                                 stdout=Compiler.DEVNULL,
                                 stderr=Compiler.DEVNULL)
        if rv == 0:
            sys.stderr.write("ok\n")
            return True
        if verbose > 0:
            if rv < 0:
                sys.stderr.write("signal {}\n".format(-rv))
            else:
                sys.stderr.write("exit {}\n".format(rv))
        return False

    def compile(self, src, verbose=0):
        """Compile source file 'src' and return the name of the object
           file generated, or False on failure.  'verbose' is passed
           through to invoke()."""
        raise NotImplemented

    def link(self, objs, exe, verbose=0):
        """Link 'objs' (a list of object file names) together to produce
           an executable named 'exe'.  Returns a possibly-corrected executable
           name, or False on failure; appropriate usage is
           >>> exe = cc.link(['a.o', 'b.o'], exe)
           'verbose' is passed through to invoke()."""
        raise NotImplemented

    @classmethod
    def probe(cls, prog, props):
        """Determine whether 'prog' is a usable compiler of the type
           represented by 'cls'.  'props' MUST be the dictionary
           returned by Compiler.identify for 'prog'.  Returns a list
           of zero or more 'cls' instances."""
        raise NotImplemented

class Unknown(Compiler):
    """A compiler we don't know how to drive."""

    @classmethod
    def probe(cls, prog, props):
        return []

class UnixCompiler(Compiler):
    """A compiler whose command line conforms to Unixy conventions."""

    def compile(self, src, verbose=0):
        obj = self.objname(src)
        if self.invoke(["-o", obj, "-c", src], obj, verbose):
            return obj
        return False

    def link(self, objs, exe, verbose=0):
        if self.invoke(["-o", exe] + objs + self.libs, exe, verbose):
            return exe
        return False

class Clang(UnixCompiler):
    """A version of Clang from the LLVM project."""

    @classmethod
    def probe(cls, prog, props):
        assert props["cc"] == "clang"

        if props["ccmaj"] < 3: # assumed too old
            return []

        need_cxx11 = props["cxx11"] == 0
        try_libcxx = props["lib"] != "llvm"
        try_libgnu = props["lib"] != "gnu"

        flags = []
        if need_cxx11:
            flags.append("-std=c++11")
            props = Compiler.identify(prog, flags)
        flags.extend(("-g", "-O2", "-Wall", "-Wextra", "-I."))

        compilers = []
        if props["cxx11"] == 1:
            compilers.append(cls(prog, props, flags, ()))

        if try_libcxx:
            nflags = flags[:]
            nflags[1:1] = ("-stdlib=libc++",)
            nprops = Compiler.identify(prog, nflags)
            if nprops["cxx11"] == 1 and nprops["lib"] == "llvm":
                compilers.append(cls(prog, nprops, nflags, ()))

        if try_libgnu:
            nflags = flags[:]
            nflags[1:1] = ("-stdlib=libstdc++",)
            nprops = Compiler.identify(prog, nflags)
            if nprops["cxx11"] == 1 and nprops["lib"] == "gnu":
                compilers.append(cls(prog, nprops, nflags, ()))

        return compilers

class Gcc(UnixCompiler):
    """A version of GCC from the GNU project."""

    @classmethod
    def probe(cls, prog, props):
        assert props["cc"] == "gcc"

        if (props["ccmaj"] < 4 or
            (props["ccmaj"] == 4 and props["ccmin"] < 7)): # assumed too old
            return []

        need_cxx11 = props["cxx11"] == 0
        try_libcxx = props["lib"] != "llvm"

        flags = []
        if need_cxx11:
            flags.append("-std=c++11")
            props = Compiler.identify(prog, flags)
            if props["cxx11"] == 0:
                return []
        flags.extend(("-g", "-O2", "-Wall", "-Wextra", "-I."))

        compilers = [cls(prog, props, flags, ())]

        # GCC can be persuaded to use libc++ but it involves more work
        # than for clang.  If anyone has a better idea than this hardwired
        # list of possible locations for libc++'s headers, please let me know.
        libcxxinc = None
        for loc in ["/include",
                    "/usr/include",
                    "/usr/local/include",
                    "/opt/include",
                    "/opt/local/include",
                    "/opt/local/libexec/llvm-3.0/lib" # MacPorts, sigh
                    ]:
            if os.path.isfile(loc + "/c++/v1/iosfwd"):
                libcxxinc = loc + "/c++/v1"

        if try_libcxx and libcxxinc is not None:
            nflags = flags + ["-nostdinc++", "-isystem", libcxxinc]
            nprops = Compiler.identify(prog, nflags)
            if nprops["lib"] == "llvm":
                compilers.append(cls(prog, nprops, nflags,
                                     ("-nodefaultlibs",
                                        "-lc++", "-lc", "-lgcc_s")))
        return compilers

def find_compilers():
    compiler_classes = collections.defaultdict(lambda: Unknown,
                                               gcc=Gcc,
                                               clang=Clang)

    executables = set()
    path = os.getenv('PATH')
    if path is not None:
        pathv = path.split(os.pathsep)
    else:
        pathv = ["/usr/local/bin", "/usr/bin", "/bin"]

    for cmd in ["g++", "clang++"]:
        for path in pathv:
            for ver in glob.iglob(os.path.join(path, cmd) + "*"):
                rp = util.unwrap_script(os.path.realpath(ver))
                if not rp: continue
                executables.add(rp)

    compilers = []
    for ex in executables:
        props = Compiler.identify(ex)
        compilers.extend(compiler_classes[props["cc"]].probe(ex, props))
    return compilers

if __name__ == '__main__':
    compilers = find_compilers()
    for cc in compilers:
        cc.compile("fmt.cc", verbose=1)
