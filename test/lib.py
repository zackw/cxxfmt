# Test utility library.

import glob
import os
import re
import subprocess
import sys
import tempfile

try:
    __readlink = os.readlink
    def _readlink(path):
        try:
            target = __readlink(path)
            if target.startswith('/'): return target
            return os.path.normpath(os.path.join(os.path.dirname(path), target))
        except OSError:
            return path
except AttributeError:
    def _readlink(path):
        return path

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

    def __init__(self, argv):
        self.argv = argv
        self.otag = re.sub("[^A-Za-z0-9-]", "-", argv[0])
        if os.name == "nt" or os.name == "ce":
            self.otag += ".obj"
        else:
            self.otag += ".o"

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
            rv = subprocess.call(argv,
                                 stdin=Compiler.devnull,
                                 stdout=Compiler.devnull,
                                 stderr=Compiler.devnull)
        if rv == 0:
            return True
        if verbose == 0:
            return False

        if rv < 0:
            sys.stderr.write("{} {}: signal {}\n".format(argv[0], label, -rv))
        else:
            sys.stderr.write("{} {}: exit {}\n".format(argv[0], label, rv))
        return False

    def compile(self, src, obj, verbose=0):
        return self.invoke(["-c", "-o", obj, src], src, verbose)

    def link(self, objs, exe, verbose=0):
        return self.invoke(["-o", exe] + objs, exe, verbose)

    def probe(self):
        return self.compile("fmt.cc", self.objname("fmt.cc"))

    @staticmethod
    def find_compilers():
        executables = set()
        path = os.getenv('PATH')
        if path is not None:
            pathv = path.split(os.pathsep)
        else:
            pathv = ["/usr/local/bin", "/usr/bin", "/bin"]

        for cmd in ["g++", "clang++"]:
            for path in pathv:
                for ver in glob.iglob(os.path.join(path, cmd) + "*"):
                    executables.add(_readlink(ver))

        compilers = []
        for ex in executables:
            for extra_args in [ ["-g", "-O2", "-I."],
                                ["-g", "-O2", "-I.", "-std=c++11"],
                                ["-g", "-O2", "-I.", "-std=c++0x"] ]:
                c = Compiler([ex] + extra_args)
                if c.probe():
                    compilers.append(c)
                    break # don't bother with the other possible extra args

        return compilers

if __name__ == '__main__':
    compilers = Compiler.find_compilers()
    for c in compilers:
        print " ".join(c.argv)

