# Test driver for cxxfmt.

# Copyright 2012, 2013 Zachary Weinberg <zackw@panix.com>.
# Use, modification, and distribution are subject to the
# Boost Software License, Version 1.0.  See the file LICENSE
# or http://www.boost.org/LICENSE_1_0.txt for detailed terms.

import ConfigParser
import contextlib
import errno
import itertools
import json
import os
import os.path
import subprocess
import sys
import tempfile

#
# Utility functions
#

@contextlib.contextmanager
def mkstemp_autodel(suffix="", prefix="tmp", dir=None, text=False,
                    contents=None):
    pathname = None
    try:
        (handle, pathname) = tempfile.mkstemp(suffix, prefix, dir, text)
        if contents is not None:
            os.write(handle, contents)
        os.close(handle)
        yield pathname
    finally:
        if pathname is not None:
            try:
                os.unlink(pathname)
            except OSError, e:
                if e.errno != errno.ENOENT:
                    raise

# credit to stackoverflow user 'Obtuse':
# http://stackoverflow.com/a/6849299/388520
class lazy_property(object):
    """Decorator for an attribute whose value is to be lazily computed
       on first use.  Apply to a method which computes the value.
       Overwrites itself with the computed value upon invocation."""

    def __init__(self, fget):
        self.__func__ = fget
        self.__name__ = fget.__name__

    def __get__(self, obj, cls):
        if obj is None:
            obj = cls
        value = self.__func__(obj)
        setattr(obj, self.__name__, value)
        return value
#
# Compiler invocation
#

class CompilerTraits(object):
    """Interface for traits classes that describe the peculiarities of
       a particular family of compilers."""

    def compile_cmd(self, src, obj, tag):
        """Return an argument vector which will compile source file
           'src' into object file 'obj', with COMPILER_NAME defined as
           a preprocessor macro which expands to a string constant whose
           contents are 'tag'."""
        raise NotImplemented

    def link_cmd(self, objs, libs, exe):
        """Return an argument vector which will link object files OBJS
           and libraries LIBS to produce executable EXE."""
        raise NotImplemented

    def version_cmd(self):
        """Return an argument vector which will cause the compiler to
           identify itself."""
        raise NotImplemented

    def probe_flags(self):
        """Generate a sequence of possible additional command line
           arguments to try with this compiler.  Each list entry
           should be a 2-tuple whose first entry is additional 'flags'
           and whose second entry is additional 'libs'."""
        raise NotImplemented

class CT_Unix(CompilerTraits):
    """A compiler whose command line conforms to Unixy conventions."""

    def compile_cmd(self, src, obj, tag):
        DCOMPILER_NAME = "-DCOMPILER_NAME=" + json.dumps(tag)
        return [ DCOMPILER_NAME, "-I.", "-O2", "-o", obj, "-c", src ]

    def link_cmd(self, objs, libs, exe):
        return [ "-o", exe ] + objs + libs

    def version_cmd(self):
        return [ "--version" ]

class CT_Gcc(CT_Unix):
    """GNU Compiler Collection."""
    def probe_flags(self):
        return [ ( [], [] ),
                 ( ["-std=c++11"], [] ) ]

class CT_Clang(CT_Unix):
    """LLVM compilers."""
    def probe_flags(self):
        return [ ( [], [] ),
                 ( ["-std=c++11"], [] ),
                 ( ["-stdlib=libc++"], [] ),
                 ( ["-std=c++11", "-stdlib=libc++"], [] ) ]

class Compiler(object):
    """A particular compiler installed on this computer, which can be
       invoked to compile and link programs"""

    def __init__(self, prog, flags, libs, props, traits):
        """Constructor for Compiler instances.  'prog' is the compiler
           executable.  'flags' are extra command line arguments to
           pass to all invocations, and 'libs' are extra command line
           arguments to pass to linking invocations (after all the
           object files).  'props' is a dictionary of properties
           describing this compiler (see the 'identify' static method),
           and 'traits' is the traits class to use to construct
           command lines.

           Normally you should not use this directly; use
           'probe_compilers' or 'load_compilers' instead."""
        self.prog = prog
        self.flags = flags
        self.libs = libs
        self.traits = traits
        for k, v in props.iteritems(): setattr(self, k, v)

    def __cmp__(self, other):
        return (cmp(self.tag, other.tag) or
                cmp(self.prog, other.prog) or
                cmp(id(self), id(other)))

    def objname(self, src):
        """Return an appropriately labeled name for an object file
           compiled from source file 'src' with this compiler."""
        return os.path.splitext(src)[0] + self.otag

    def exename(self, base):
        """Return an appropriate name for an executable generated by this
           compiler, beginning with 'base'."""
        return os.path.splitext(base)[0] + self.etag

    def compile(self, src, verbose=1):
        """Compile source file 'src'.  The object file will be named
           self.objname(src).  Returns True on success, False on failure.
           'verbose' is passed through to invoke()."""
        obj = self.objname(src)
        return self.invoke(self.traits.compile_cmd(src, obj, self.tag),
                           obj, verbose)

    def link(self, objs, exe, verbose=1):
        """Link 'objs' (a list of object file names) together.  The
           resulting executable will be named self.exename(exe).
           Returns True on success, False on failure.
           'verbose' is passed through to invoke()."""
        exe = self.exename(exe)
        return self.invoke(self.traits.link_cmd(objs, self.libs, exe),
                           exe, verbose)

    @lazy_property
    def DEVNULL(_):
        """Read-write file handle on /dev/null.  If possible,
           delegates to subprocess; otherwise opens a global handle on
           os.devnull itself.  If possible, that handle is marked
           close-on-exec.

           N.B. this is not a global because descriptors do not apply
           to lookups in module objects, and thus @lazy_property does
           not work in that context."""
        try:
            return subprocess.DEVNULL
        except AttributeError:
            try:
                return os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
            except AttributeError:
                return os.open(os.devnull, os.O_RDWR)

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
            rv = subprocess.call(argv, stdin=self.DEVNULL)
        else:
            if verbose == 1:
                sys.stderr.write("{} {}...".format(argv[0], label))
            rv = subprocess.call(argv,
                                 stdin=self.DEVNULL,
                                 stdout=self.DEVNULL,
                                 stderr=self.DEVNULL)
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

    def save(self, cfg):
        """Stash everything we know about this compiler in a config file."""
        sect = self.tag
        cfg.add_section(sect)
        for v in vars(self):
            if v == 'tag': pass
            elif v == 'traits':
                cfg.set(sect, v, getattr(self, v).__class__.__name__)
            elif v == 'flags' or v == 'libs':
                cfg.set(sect, v, json.dumps(getattr(self, v)))
            else:
                cfg.set(sect, v, getattr(self, v))

    @classmethod
    def load(cls, cfg, sect):
        """Load one Compiler object from section SECT of config file CFG."""
        prog = cfg.get(sect, 'prog')
        flags = json.loads(cfg.get(sect, 'flags'))
        libs = json.loads(cfg.get(sect, 'libs'))
        traits = globals()[cfg.get(sect, 'traits')]()
        props = { 'tag': sect }
        for k, v in cfg.items(sect):
            if k != 'prog' and k != 'flags' and k != 'libs' and k != 'traits':
                props[k] = v
        return cls(prog, flags, libs, props, traits)

    @classmethod
    def load_compilers(cls, cfgfile):
        """Load all Compiler objects defined in config file CFGFILE."""
        cfg = ConfigParser.RawConfigParser()
        cfg.read(cfgfile)
        return [ cls.load(cfg, sect) for sect in cfg.sections() ]

    @staticmethod
    def save_compilers(compilers, cfgfile):
        """Write all Compiler objects to config file CFGFILE."""
        cfg = ConfigParser.RawConfigParser()
        for cc in compilers: cc.save(cfg)
        cfg.write(open(cfgfile, "w"))

    _identify_source = None
    _identify_source_gen = None
    @classmethod
    def identify_source(cls):
        if cls._identify_source is None:
            cls._identify_source_gen = mkstemp_autodel(suffix=".cc",
                                                       prefix="id-",
                                                       text=True,
                                                       contents=r"""
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
""")
            cls._identify_source = cls._identify_source_gen.__enter__()
        return cls._identify_source

    @classmethod
    def identify(cls, prog, extra_args, verbose):
        """Subroutine of 'probe_compilers' (below).  Find out which version of
           which compiler 'prog' is, and which C++ runtime library it
           offers, when invoked with 'extra_args'.  'prog' should be
           an absolute pathname to an executable."""

        source = cls.identify_source()
        with mkstemp_autodel(suffix=".exe", prefix="id-") as exe:
            try:
                # This is how g++ and clang++ want to be invoked.
                argv = [prog] + extra_args + ["-o", exe, source]
                if verbose >= 2:
                    sys.stderr.write(" ".join(argv) + "\n")
                    cc_stderr = None
                else:
                    cc_stderr = cls.DEVNULL
                    if verbose == 1:
                        sys.stderr.write("probe " + " ".join(argv[:-3]) + "...")
                subprocess.check_call(argv,
                                      stdin=cls.DEVNULL,
                                      stdout=cls.DEVNULL,
                                      stderr=cc_stderr)
                output = subprocess.check_output(exe)
                fail = False

            except subprocess.CalledProcessError, e:
                # Retry with appropriate switches for MSVC should go here.
                # I am getting a headache just looking at its documentation,
                # so it can wait.
                if verbose >= 1:
                    if e.returncode < 0:
                        sys.stderr.write("{} signal {}\n".format(e.cmd[0],
                                                                 -e.returncode))
                    else:
                        sys.stderr.write("{} exit {}\n".format(e.cmd[0],
                                                               e.returncode))

                output = """{ "cxx11" : 0,
                              "cc"    : "unknown",
                              "ccmaj" : 0,
                              "ccmin" : 0,
                              "lib"   : "unknown" }"""
                fail = True

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
            etag += ".x"

        props["tag"] = tag
        props["otag"] = otag
        props["etag"] = etag

        if verbose >= 1 and not fail:
            sys.stderr.write(tag)
            if props["cxx11"] == 1:
                sys.stderr.write(" (ok)\n")
            else:
                sys.stderr.write(" (not C++11)\n")
        return props

    @classmethod
    def pick_traits(cls, prog):
        """Subroutine of probe_compilers().  Pick the appropriate
        traits class for the compiler named 'prog'."""
        try:
            output = subprocess.check_output([prog] + CT_Unix().version_cmd(),
                                             stderr=cls.DEVNULL)
        except CalledProcessError:
            return None

        output = output.lower()
        if "gcc" in output: return CT_Gcc()
        elif "clang" in output: return CT_Clang()
        else: return None

    @classmethod
    def probe_compilers(cls, progs, verbose=0):
        compilers = []
        for prog in progs:
            traits = cls.pick_traits(prog)
            if traits is None:
                if verbose >= 1:
                    sys.stderr.write("no known traits for " + prog + "\n")
                continue

            for flags, libs in traits.probe_flags():
                props = cls.identify(prog, flags + libs, verbose)
                if props["cxx11"] == 1:
                    compilers.append(cls(prog, flags, libs, props, traits))

        return compilers

def find_compilers(candidates, verbose):
    if len(candidates) == 0:
        candidates = ["g++", "clang++"]
    candidates = set(candidates)

    compilers = []

    if os.path.exists("compilers.ini"):
        compilers = Compiler.load_compilers("compilers.ini")
        for cc in compilers:
            candidates.discard(cc.prog)

    compilers.extend(Compiler.probe_compilers(candidates, verbose))

    if len(compilers) == 0:
        raise RuntimeError("no usable compilers identified")
    Compiler.save_compilers(compilers, "compilers.ini")
    return compilers

#
# Test jobs and their interdependencies.
#

class Job(object):
    """Base class for test jobs.  A job is executed at most once, and
       execution either succeeds or fails.  Jobs depend on other jobs;
       a job cannot execute until all of its dependencies succeed.
       If a job fails, it is not retried even if it's in some other
       job's dependencies.

       Jobs may or may not produce an 'output', which is a file in the
       filesystem.  If a job does produce output, and that output is
       newer (according to os.stat) than the outputs of all its
       dependencies, then we assume that the job has succeeded already
       and does not need to be rerun.

       A base Job object doesn't do anything when executed other than
       invoke all of its dependencies.  Subclasses can override the
       run() method to do something."""

    def __init__(self, verbose, deps, output=None):
        self.deps    = deps
        self.output  = output
        self.verbose = verbose
        self.result  = None # not yet executed
        self.mtime_  = None # not yet checked

    def update_mtime(self):
        if self.output is None: return
        try:
            self.mtime_ = os.stat(self.output).st_mtime
        except OSError, e:
            if e.errno != errno.ENOENT:
                raise
            self.mtime_ = 0 # doesn't exist = out of date

    def mtime(self):
        if self.output is None: return 0 # no output = always out of date
        if self.mtime_ is None: self.update_mtime()
        return self.mtime_

    def uptodate(self):
        my_mtime = self.mtime()
        if my_mtime == 0: return False # automatically out of date

        for dep in self.deps:
            if not dep.uptodate(): return False
            if my_mtime < dep.mtime(): return False

        return True

    def execute(self):
        if self.result is not None:
            return self.result
        if self.uptodate():
            self.result = True
            return True
        for dep in self.deps:
            dep_result = dep.execute()
            if dep_result is not True:
                self.result = dep_result
                return dep_result
        self.result = self.run()
        if self.result is True: self.update_mtime()
        return self.result

    def run(self):
        return True  # success

class FileDep(Job):
    """Pseudo-job to model a dependency on a file that is not created
       through this system.  Cannot itself have dependencies.  If the
       file doesn't exist, run() just fails."""

    def __init__(self, output):
        Job.__init__(self, 0, [], output)

    def run(self):
        sys.stderr.write("*** Don't know how to create {!r}.\n"
                         .format(self.output))
        return False

class CompileJob(Job):
    """Job to compile one source file with a specified compiler.
       Dependencies have no particular significance."""
    def __init__(self, verbose, deps, cc, src):
        self.cc  = cc
        self.src = src
        Job.__init__(self, verbose, deps, output=cc.objname(src))

    def run(self):
        return self.cc.compile(self.src)

class LinkJob(Job):
    """Job to link one or more object files with a specified compiler.
       Each CompileJob in the dependencies contributes its object file
       to the link."""
    def __init__(self, verbose, deps, cc, exebase):
        self.cc = cc
        self.exebase = exebase
        self.objs = [dep.output for dep in deps if isinstance(dep, CompileJob)]
        Job.__init__(self, verbose, deps, output=cc.exename(exebase))

    def run(self):
        return self.cc.link(self.objs, self.exebase)

class RunJob(Job):
    """Job to run a program with arguments."""
    def __init__(self, verbose, deps, argv, output=None):
        Job.__init__(self, verbose, deps, output)
        self.argv = argv

    def run(self):
        if self.argv[0].endswith(".py"):
            argv = [sys.executable] + self.argv
        else:
            argv = self.argv

        if self.verbose == 1:
            sys.stderr.write(self.argv[0] + "...")
        elif self.verbose == 2:
            sys.stderr.write(" ".join(argv) + "\n")

        rv = subprocess.call(argv)
        self.exitcode = rv
        if rv == 0:
            if self.verbose == 1:
                sys.stderr.write("ok\n")
            return True
        if verbosity > 0:
            if rv < 0:
                sys.stderr.write("signal {}\n".format(-rv))
            else:
                sys.stderr.write("exit {}\n".format(rv))
        return False

class TestJob(RunJob):
    """Job to run a test program, namely the program generated by the
       first LinkJob in the dependencies. 'args' can be used to specify
       extra arguments to this program."""
    def __init__(self, verbose, deps, args=[]):
        exe = None
        for dep in deps:
            if isinstance(dep, LinkJob):
                exe = dep.output
                break
        if exe is None:
            raise ValueError("no LinkJob in dependencies")

        if verbose >= 2:
            if len(args) >= 1 and args[-1] == "-q":
                args.pop()
            else:
                args.append("-v")

        RunJob.__init__(self, verbose, deps, [os.path.join(".", exe)] + args)

#
# In-tree main test driver.
#

def main():
    verbose = 1
    args = sys.argv[1:]
    if len(args) > 0:
        if args[0] == '-v':
            verbose += 1
            args.pop(0)
        elif args[0] == '-q':
            verbose -= 1
            args.pop(0)

    compilers = find_compilers(args, verbose)

    testgen = RunJob(verbose,
                     [FileDep("test_fmt_gen.py")],
                     ["test_fmt_gen.py", "test_fmt.cc"],
                     output="test_fmt.cc")
    fmtccdep = FileDep("fmt.cc")
    fmthdep  = FileDep("fmt.h")

    cjobs = [ [ CompileJob(verbose, [testgen, fmthdep], cc, "test_fmt.cc"),
                CompileJob(verbose, [fmtccdep, fmthdep], cc, "fmt.cc") ]
              for cc in compilers ]
    ljobs = [ LinkJob(verbose, objs, cc, "test_fmt")
              for (objs, cc) in zip(cjobs, compilers) ]
    tjobs = [ TestJob(verbose, [ljob], ["-q"])
              for ljob in ljobs ]

    all = Job(verbose, tjobs)
    all.execute()

main()
