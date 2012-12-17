#
# Test jobs and their interdependencies.
#

assert __name__ != '__main__'
from __main__ import verbosity

import os
import os.path
import subprocess
import sys

import compiler
import util

class Job(object):
    """Base class for test jobs.  A job is executed at most once, and
       execution either succeeds or fails.  Jobs depend on other jobs;
       a job cannot execute until all of its dependencies succeed.
       If a job fails, it is not retried even if it's in some other
       job's dependencies.

       A base Job object doesn't do anything when executed other than
       invoke all of its dependencies.  Subclasses can override the
       run() method to do something."""

    def __init__(self, deps):
        self.deps   = deps
        self.result = None # not yet executed

    def execute(self):
        if self.result is not None:
            return self.result
        for dep in self.deps:
            result = dep.execute()
            if result is not True:
                self.result = result
                return result
        result = self.run()
        self.result = result
        return result

    def run(self):
        return True  # success

class CompileJob(Job):
    """Job to compile one source file with a specified compiler.
       Dependencies have no particular significance."""
    def __init__(self, deps, cc, src):
        Job.__init__(self, deps)
        self.cc  = cc
        self.src = src
        self.obj = cc.objname(src)

    def run(self):
        return self.cc.compile(self.src)

class LinkJob(Job):
    """Job to link one or more object files with a specified compiler.
       Each CompileJob in the dependencies contributes its object file
       to the link."""
    def __init__(self, deps, cc, exebase):
        Job.__init__(self, deps)
        self.cc = cc
        self.exebase = exebase
        self.exe = cc.exename(exebase)
        self.objs = [dep.obj for dep in deps if isinstance(dep, CompileJob)]

    def run(self):
        return self.cc.link(self.objs, self.exebase)

class RunJob(Job):
    """Job to run a program with arguments."""
    def __init__(self, deps, argv):
        Job.__init__(self, deps)
        self.argv = argv

    def run(self):
        if self.argv[0].endswith(".py"):
            argv = [sys.executable] + self.argv
        else:
            argv = self.argv

        if verbosity == 1:
            sys.stderr.write(self.argv[0] + "...")
        elif verbosity == 2:
            sys.stderr.write(" ".join(argv) + "\n")

        rv = subprocess.call(argv)
        self.exitcode = rv
        if rv == 0:
            if verbosity == 1:
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
    def __init__(self, deps, args=[]):
        exe = None
        for dep in deps:
            if isinstance(dep, LinkJob):
                exe = dep.exe
                break
        if exe is None:
            raise ValueError("no LinkJob in dependencies")

        RunJob.__init__(self, deps, [os.path.join(".", exe)] + args)