# Test utility library.

import collections
import glob
import json
import os
import subprocess
import sys

#
# Misc utilities
#

def is_script(path):
    with open(path, "r") as f:
        return f.read(2) == "#!"

# This should be in subprocess, but it ain't.
def check_io(*popenargs, **kwargs):
    if 'stdout' in kwargs:
        raise ValueError('stdout argument not allowed, it will be overridden.')
    if 'stdin' in kwargs:
        raise ValueError('stdin argument not allowed, it will be overridden.')
    if 'input' in kwargs:
        inputdata = kwargs['input']
        del kwargs['input']
    else:
        inputdata=""
    process = subprocess.Popen(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               *popenargs, **kwargs)
    output, unused_err = process.communicate(inputdata)
    retcode = process.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]
        raise subprocess.CalledProcessError(retcode, cmd, output=output)
    return output

#
# Test case generation utilities
#

class TestBlock(object):
    def __init__(self, mod, name, casetype, generator):
        self.mod = mod
        self.name = name
        self.casetype = casetype
        self.generator = generator
        self.d = self.__dict__

    def __cmp__(self, other):
        # primary sort alpha by module
        if self.mod < other.mod: return -1
        if self.mod > other.mod: return 1

        # sort any block named 'simple' to the top within its module
        if self.name == "simple" and other.name != "simple": return -1
        if self.name != "simple" and other.name == "simple": return 1

        # otherwise, alphabetical
        if self.name < other.name: return -1
        if self.name > other.name: return 1
        return 0

    def fullname(self):
        return "{mod}.{name}".format(**self.d)

    def write_cases(self, outf):
        outf.write("const {casetype} {mod}_{name}[] = {{\n".format(**self.d))
        for case in self.generator():
            outf.write("  { " + case + " },\n")
        outf.write("};\n\n")

    def write_tblock_obj(self, outf):
        outf.write("const tblock<{casetype}> "
                   "{mod}_{name}_b(\"{mod}.{name}\", {mod}_{name});\n"
                   .format(**self.d))

    def write_tblocks_entry(self, outf):
        outf.write("  &{mod}_{name}_b,\n".format(**self.d));

class TestGenerator(object):
    def __init__(self):
        self.blocks = []
        self.duplicate_preventer = set()

    def add_block(self, block):
        f = block.fullname()
        if f in self.duplicate_preventer:
            raise KeyError(f + " already registered")
        self.blocks.append(block)
        self.duplicate_preventer.add(f)

    def add_module(self, name, casetype, contents):
        for k, v in contents.iteritems():
            if k.startswith('g_'):
                self.add_block(TestBlock(name, k[2:], casetype, v))

    def generate(self, outf):
        self.blocks.sort()

        for b in self.blocks: b.write_cases(outf)
        for b in self.blocks: b.write_tblock_obj(outf)

        outf.write("\nconst vector<const i_tblock*> tblocks = {\n")
        for b in self.blocks: b.write_tblocks_entry(outf)
        outf.write("};\n")


def generate_mod(outf, name, casetype, contents):
    g = TestGenerator()
    g.add_module(name, casetype, contents)
    g.generate(outf)

#
# Compiler detection and invocation
#

class Compiler(object):
    devnull = None

    @staticmethod
    def identify(prog, extra_args=[]):
        identify_source = """\
// We have to include some C++ library header to get the library's
// identifying macros defined.  There are no C++ library headers that
// define nothing but macros, so we put a marker after this inclusion
// and strip out all the leading junk from Python.  Since we have to
// postprocess the output anyway, this is an excuse not to bother with -P.

#include <iosfwd>

// just to be sure
#undef F
#undef FF

#define F(a,b) FF(a,b)
#define FF(a,b) a##.##b

%%
{
#if __cplusplus >= 201103L
  "cxx11" : 1,
#else
  "cxx11" : 0,
#endif
#if defined _MSC_VER
  "cc"    : "msvc",
  "ccver" : 0,
#elif defined __clang__ // N.B. clang defines __GNUC__
  "cc"    : "clang",
  "ccver" : F(__clang_major__,__clang_minor__),
#elif defined __GNUC__
  "cc"    : "gcc",
  "ccver" : F(__GNUC__,__GNUC_MINOR__),
#else
  "cc"    : "unknown",
  "ccver" : 0,
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
        if Compiler.devnull is None:
            Compiler.devnull = open(os.devnull, "r+")
        try:
            # This is how g++ and clang++ want to be invoked.
            output = check_io([prog, "-E", "-xc++"] + extra_args + ["-"],
                              stderr=Compiler.devnull,
                              input=identify_source)
        except subprocess.CalledProcessError:
            # Retry with appropriate switches for MSVC should go here.
            # I am getting a headache just looking at its documentation,
            # so it can wait.
            return { "cxx11" : 0,
                     "cc"    : "unknown",
                     "ccver" : 0,
                     "lib"   : "unknown" }

        props = json.loads("".join(
                  l for l in output[output.rfind("%%")+2:].splitlines()
                    if len(l) > 0 and l[0] != '#'))

        otag = ("-" + props["cc"] +
                "-" + str(props["ccver"]) +
                "-lib" + props["lib"] + ".o")
        if os.name == "nt" or os.name == "ce":
            otag += "bj"

        props["otag"] = otag
        return props

    def __init__(self, argv, otag):
        self.argv = argv
        self.otag = otag

    def objname(self, src):
        return os.path.splitext(src)[0] + self.otag

    # verbose=0: total silence.
    # verbose=1: report success or failure.
    # verbose=2: report invocation and error messages.
    def invoke(self, args, label, verbose):
        if verbose < 0 or verbose > 2:
            raise ValueError("bad verbosity {}".format(verbose))

        if Compiler.devnull is None:
            Compiler.devnull = open(os.devnull, "r+")

        argv = self.argv + args
        if verbose == 2:
            sys.stderr.write(" ".join(argv) + "\n")
            rv = subprocess.call(argv, stdin=Compiler.devnull)
        else:
            if verbose == 1:
                sys.stderr.write("{} {}...".format(argv[0], label))
            rv = subprocess.call(argv,
                                 stdin=Compiler.devnull,
                                 stdout=Compiler.devnull,
                                 stderr=Compiler.devnull)
        if rv == 0:
            sys.stderr.write("ok\n")
            return True
        if verbose > 0:
            if rv < 0:
                sys.stderr.write("signal {}\n".format(-rv))
            else:
                sys.stderr.write("exit {}\n".format(rv))
        return False

    def compile(self, src, obj, verbose=0):
        raise NotImplemented

    def link(self, objs, exe, verbose=0):
        raise NotImplemented

    @staticmethod
    def probe(prog, props):
        raise NotImplemented

class Unknown(Compiler):
    @staticmethod
    def probe(prog, props):
        return []

class UnixCompiler(Compiler):
    def __init__(self, prog, flags, libs, otag):
        Compiler.__init__(self, [prog] + flags, otag)
        self.libs = libs

    def compile(self, src, obj, verbose=0):
        return self.invoke(["-o", obj, "-c", src], obj, verbose)

    def link(self, objs, exe, verbose=0):
        return self.invoke(["-o", exe] + objs + self.libs, exe, verbose)

class Clang(UnixCompiler):
    @staticmethod
    def probe(prog, props):
        assert props["cc"] == "clang"

        if props["ccver"] < 3.0: # assumed too old
            return []

        need_cxx11 = props["cxx11"] == 0
        try_libcxx = props["lib"] != "llvm"
        try_libgnu = props["lib"] != "gnu"

        argv = []
        if need_cxx11:
            argv.append("-std=c++11")
            if Compiler.identify(prog, argv)["cxx11"] == 0:
                return []

        argv.extend(("-g", "-O2", "-Wall", "-Wextra", "-I."))

        compilers = []
        compilers.append(Clang(prog, argv, [], props["otag"]))

        if try_libcxx:
            args = argv
            args[1:1] = ("-stdlib=libc++",)
            nprops = Compiler.identify(prog, args)
            if nprops["lib"] == "llvm":
                compilers.append(Clang(prog, args, [], nprops["otag"]))
        if try_libgnu:
            args = argv
            args[1:1] = ("-stdlib=libstdc++",)
            nprops = Compiler.identify(prog, args)
            if nprops["lib"] == "gnu":
                compilers.append(Clang(prog, args, [], nprops["otag"]))

        return compilers

class Gcc(UnixCompiler):
    @staticmethod
    def probe(prog, props):
        assert props["cc"] == "gcc"

        if props["ccver"] < 4.7: # assumed too old
            return []

        need_cxx11 = props["cxx11"] == 0
        try_libcxx = props["lib"] != "llvm"

        argv = []
        if need_cxx11:
            argv.append("-std=c++11")
            if Compiler.identify(prog, argv)["cxx11"] == 0:
                return []

        argv.extend(("-g", "-O2", "-Wall", "-Wextra", "-I."))

        compilers = []
        compilers.append(Gcc(prog, argv, [], props["otag"]))

        # GCC can be persuaded to use libc++ but it involves more work
        # than for clang.  If anyone has a better idea than this hardwired
        # list of possible locations for libc++'s headers, please let me know.
        libcxxinc = None
        for loc in ["/", "/usr", "/usr/local", "/opt", "/opt/local"]:
            if os.path.isfile(loc + "/include/c++/v1/iosfwd"):
                libcxxinc = loc + "/include/c++/v1"
        if try_libcxx and libcxxinc is not None:
            args = argv + ["-nostdinc++", "-isystem", libcxxinc]
            nprops = Compiler.identify(prog, args)
            if nprops["lib"] == "llvm":
                compilers.append(Gcc(prog, args,
                                     ["-nodefaultlibs",
                                        "-lc++", "-lc", "-lgcc_s"],
                                     nprops["otag"]))
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
                rp = os.path.realpath(ver)
                if rp in executables: continue
                if is_script(rp): continue
                executables.add(rp)

    compilers = []
    for ex in executables:
        props = Compiler.identify(ex)
        compilers.extend(compiler_classes[props["cc"]].probe(ex, props))
    return compilers

if __name__ == '__main__':
    compilers = find_compilers()
    for cc in compilers:
        cc.compile("fmt.cc", cc.objname("fmt.cc"), verbose=1)
