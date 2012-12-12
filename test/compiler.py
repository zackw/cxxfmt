#
# Compiler detection and invocation
#

if __name__ == '__main__':
    verbosity = 2
else:
    from __main__ import verbosity

import collections
import glob
import json
import os
import os.path
import subprocess
import sys

import util

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

        identify_source = r"""
// Thanks largely to the clown show that is MacPorts, we have to
// compile and run a test program to make absolutely sure that the
// particular combination of compiler and library we're trying
// actually works.  If the compiler is already in C++11 mode, we
// include <type_traits> even though it's not actually used, to detect
// more possible incompatibilities between the compiler and the library.

#include <iostream>
#if __cplusplus >= 201103L
#include <type_traits>
#endif

using std::cout;
int main()
{
  cout << "{\n"
#if __cplusplus >= 201103L
       << "  \"cxx11\" : 1,\n"
#else
       << "  \"cxx11\" : 0,\n"
#endif
// clang defines __GNUC__ and might plausibly decide to define
// _MSC_VER on Windows, so check for it first.
#if defined __clang__
       << "  \"cc\"    : \"clang\",\n"
       << "  \"ccmaj\" : " << __clang_major__ << ",\n"
       << "  \"ccmin\" : " << __clang_minor__ << ",\n"
#elif defined __GNUC__
       << "  \"cc\"    : \"gcc\",\n"
       << "  \"ccmaj\" : " << __GNUC__ << ",\n"
       << "  \"ccmin\" : " << __GNUC_MINOR__ << ",\n"
#elif defined _MSC_VER
       << "  \"cc\"    : \"msvc\",\n"
       << "  \"ccmaj\" : " << _MSC_VER << ",\n"
       << "  \"ccmin\" : 0,\n"
#else
       << "  \"cc\"    : \"unknown\",\n"
       << "  \"ccmaj\" : 0,\n"
       << "  \"ccmin\" : 0,\n"
#endif
#if defined _LIBCPP_VERSION
       << "  \"lib\"   : \"llvm\"\n" // "libc++" is too generic
#elif defined __GLIBCXX__
       << "  \"lib\"   : \"gnu\"\n"
#elif defined _MSC_VER
       << "  \"lib\"   : \"ms\"\n"
#else
       << "  \"lib\"   : \"unknown\"\n"
#endif
       << "}\n";
  return 0;
}
"""

        try:
            # This is how g++ and clang++ want to be invoked.
            argv = [prog, "-xc++", "-o", "id.exe"] + extra_args + ["-"]
            if verbosity >= 2:
                sys.stderr.write(" ".join(argv) + "\n")
                cc_stderr = None
            else:
                cc_stderr = Compiler.DEVNULL
            cc_output = util.check_io(argv,
                                      stderr=cc_stderr,
                                      input=identify_source)
            output = util.check_io("./id.exe")
        except subprocess.CalledProcessError:
            # Retry with appropriate switches for MSVC should go here.
            # I am getting a headache just looking at its documentation,
            # so it can wait.
            return { "cxx11" : 0,
                     "cc"    : "unknown",
                     "ccmaj" : 0,
                     "ccmin" : 0,
                     "lib"   : "unknown" }

        props = json.loads(output)

        props["ccver"] = str(props["ccmaj"]) + "." + str(props["ccmin"])

        tag = props["cc"] + "-" + props["ccver"] + "-lib" + props["lib"]
        otag = "-" + tag
        etag = otag
        if os.name == "nt" or os.name == "ce":
            otag += ".obj"
            etag += ".exe"
        else:
            otag += ".o"

        props["tag"] = tag
        props["otag"] = otag
        props["etag"] = etag
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

    def __cmp__(self, other):
        if self.prog < other.prog: return -1
        if self.prog > other.prog: return 1
        if self.props['otag'] < other.props['otag']: return -1
        if self.props['otag'] > other.props['otag']: return 1
        return 0

    def objname(self, src):
        """Return an appropriately labeled name for an object file
           compiled from source file 'src' with this compiler."""
        return os.path.splitext(src)[0] + self.props["otag"]

    def exename(self, base):
        """Return an appropriate name for an executable generated by this
           compiler, beginning with 'base'."""
        return os.path.splitext(base)[0] + self.props["etag"]

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
        if verbose is None:
            verbose = verbosity
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
            if verbose == 1:
                sys.stderr.write("ok\n")
            return True
        if verbose > 0:
            if rv < 0:
                sys.stderr.write("signal {}\n".format(-rv))
            else:
                sys.stderr.write("exit {}\n".format(rv))
        return False

    def compile(self, src, verbose=None):
        """Compile source file 'src'.  The object file will be named
           self.objname(src).  Returns True on success, False on failure.
           'verbose' is passed through to invoke()."""
        raise NotImplemented

    def link(self, objs, exe, verbose=None):
        """Link 'objs' (a list of object file names) together.  The
           resulting executable will be named self.exename(exe).
           Returns True on success, False on failure.
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

    def compile(self, src, verbose=None):
        obj = self.objname(src)
        return self.invoke(["-DCOMPILER_NAME=\"{}\"".format(self.props["tag"]),
                            "-o", obj, "-c", src], obj, verbose)

    def link(self, objs, exe, verbose=None):
        exe = self.exename(exe)
        return self.invoke(["-o", exe] + objs + self.libs, exe, verbose)

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
            compilers.append(cls(prog, props, flags, []))

        if try_libcxx:
            nflags = flags[:]
            nflags[1:1] = ("-stdlib=libc++",)
            nprops = Compiler.identify(prog, nflags)
            if nprops["cxx11"] == 1 and nprops["lib"] == "llvm":
                compilers.append(cls(prog, nprops, nflags, []))

        if try_libgnu:
            nflags = flags[:]
            nflags[1:1] = ("-stdlib=libstdc++",)
            nprops = Compiler.identify(prog, nflags)
            if nprops["cxx11"] == 1 and nprops["lib"] == "gnu":
                compilers.append(cls(prog, nprops, nflags, []))

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

        compilers = [cls(prog, props, flags, [])]

        # GCC can be persuaded to use libc++ but it involves more work
        # than for clang.  If anyone has a better idea than this
        # hardwired list of possible locations for libc++'s headers,
        # please let me know.  The libc++ shipped with MacPorts llvm
        # 3.0 and 3.1 do not have their headers in any of these
        # directories, but they don't work with gcc anyway, so there's
        # no point trying.
        libcxxinc = None
        for loc in ["/include",
                    "/usr/include",
                    "/usr/local/include",
                    "/opt/include",
                    "/opt/local/include"
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

# This is too special-purpose to go in util.
def unwrap_script(path):
    """If 'path' is a shell script (as determined by util.is_script),
       assume that it is a wrapper around a compiler binary, and
       attempt to extract and return the name of the program it
       actually runs.

       If 'path' is not a shell script, returns it unchanged.
       If 'path' is a shell script but it couldn't figure out
       the name of the program it actually runs, returns False.

       This doesn't try very hard.  Its /raison d'^etre/ is the clang
       wrapper scripts installed by MacPorts, which we need to accept
       as compilers, and the "g++-libc++" wrapper script installed by
       libc++ on some Linux distributions, which we need to avoid.
       Failure here just means that we miss a potential compiler
       candidate, which is no big deal.
       """
    interpreter = util.is_script(path)
    if interpreter is False: return path
    if interpreter is True: return False

    # Definitely a shell script at this point.
    # We assume it is a shell script that runs a compiler, therefore
    # invoking it with "-E" and an empty .cc file will exit successfully.
    with util.mkstemp_autodel(suffix=".cc", text=True) as src:
        cmds = subprocess.check_output([interpreter, "-x", path, "-E", src],
                                       stderr=subprocess.STDOUT)
        lines = cmds.splitlines()
        lines.reverse()
        for line in lines:
            if line == "": continue
            if line[0] == "+" and src in line:
                for word in line.split():
                    if word != "+" and word != "exec":
                        if word.startswith("/"):
                            canon = os.path.realpath(word)
                            if os.path.isfile(canon):
                                return canon
                        return False


def find_compilers():
    """Identify all usable compilers on this system and return them
    as a list of Compiler objects."""
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
                rp = unwrap_script(ver)
                if not rp: continue
                rp = os.path.realpath(rp)
                # make sure we are invoking the C++ variant of the
                # compiler driver, or we may wind up failing to link
                # with the C++ runtime
                if "++" not in os.path.basename(rp):
                    if rp.endswith("cc"):
                        rp = rp[:-2] + "++"
                    else:
                        rp = rp + "++"
                if not rp or not os.path.exists(rp): continue
                executables.add(rp)

    compilers = []
    for ex in executables:
        props = Compiler.identify(ex)
        compilers.extend(compiler_classes[props["cc"]].probe(ex, props))
    compilers.sort()
    return compilers

if __name__ == '__main__':
    compilers = find_compilers()
    for cc in compilers:
        sys.stdout.write("{}: {}\n".format(cc.prog, json.dumps(cc.props)))
