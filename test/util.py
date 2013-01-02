# Test utility functions.

import contextlib
import errno
import os
import tempfile

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
