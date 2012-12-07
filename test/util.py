# Test utility functions.

import subprocess

def is_script(path):
    with open(path, "r") as f:
        return f.read(2) == "#!"

# This should be in subprocess, but it ain't.
def check_io(*popenargs, **kwargs):
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
