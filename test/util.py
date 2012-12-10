# Test utility functions.

import contextlib
import os
import os.path
import subprocess
import tempfile

@contextlib.contextmanager
def mkstemp_autodel(suffix="", prefix="tmp", dir=None, text=False,
                    contents=None):
    (handle, pathname) = tempfile.mkstemp(suffix, prefix, dir, text)
    if contents is not None:
        os.write(handle, contents)
    os.close(handle)
    yield pathname
    os.unlink(pathname)

def is_script(path):
    """Returns False if 'path' is not a script,
       True if it's a script but not a shell script,
       or the name of the shell interpreter if it's a shell script."""

    with open(path, "rU") as f:
        # check for #! before attempting to read up to a newline.
        if f.read(2) != "#!": return False
        interpreter = f.readline().split()[0]
        if interpreter.endswith("sh") and not interpreter.endswith("csh"):
            return interpreter
        return True

def unwrap_script(path):
    """If 'path' is a shell script (as determined by is_script),
       attempt to extract and return the name of the program it
       actually runs.  Returns False if 'path' is a script but it
       couldn't figure out what the script runs.  If 'path' is not a
       script, returns it unchanged."""
    interpreter = is_script(path)
    if interpreter is False: return path
    if interpreter is True: return False

    # Definitely a shell script at this point.
    with mkstemp_autodel(suffix=".cc", text=True) as src:
        cmds = subprocess.check_output([interpreter, "-x", path, "-E", src],
                                       stderr=subprocess.STDOUT)
        for line in cmds.splitlines():
            if line[0] == "+" and src in line:
                for word in line.split():
                    if word != "+" and word != "exec":
                        if word.startswith("/"):
                            canon = os.path.realpath(word)
                            if os.path.isfile(canon): return canon
                        return False

# This should be in subprocess, but it ain't.
def check_io(*popenargs, **kwargs):
    """Same as subprocess.check_output() but takes an additional argument,
       'input', allowing you to pass a string to the subprocess's stdin.
       You may not use the 'stdin' and 'input' arguments at the same time."""

    if 'stdout' in kwargs:
        raise ValueError('stdout argument not allowed, it will be overridden.')
    if 'input' in kwargs:
        if 'stdin' in kwargs:
            raise ValueError("'stdin' and 'input' may not be used together.")
        inputdata = kwargs['input']
        del kwargs['input']
        kwargs['stdin'] = subprocess.PIPE
    else:
        inputdata = None
    process = subprocess.Popen(stdout=subprocess.PIPE, *popenargs, **kwargs)
    output, unused_err = process.communicate(inputdata)
    retcode = process.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = popenargs[0]
        raise subprocess.CalledProcessError(retcode, cmd, output=output)
    return output

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
