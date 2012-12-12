#
# Generate formatting test cases for simple string constants.
#

if __name__ == '__main__':
    verbosity = 1
else:
    from __main__ import verbosity

import generator
import compiler
import job

words = [ '', 'i', 'of', 'sis', 'fice', 'drisk', 'elanet', 'hippian',
          'botanist', 'synaptene', 'cipherhood', 'schizognath' ]

aligns = [ '', '<', '>', '^', 'L<', 'R>', 'C^' ]

maxw = len(words) + 3

def output(spec, val):
    return '"{}", "{}", "{}"'.format(spec, spec.format(val), val)

def g_simple():
    for w in words:
        for a in aligns:
            yield output('{:'+a+'}', w)

def g_width():
    for width in xrange(1, maxw):
        formats = ['{{:{}{}}}'.format(a, width) for a in aligns]
        for w in words:
            for f in formats:
                yield output(f,w)

def g_prec():
    for prec in xrange(maxw):
        formats = ['{{:{}.{}}}'.format(a, prec) for a in aligns]
        for w in words:
            for f in formats:
                yield output(f,w)

def g_wnp():
    for width in xrange(1, maxw):
        for prec in xrange(maxw):
            formats = ['{{:{}{}.{}}}'.format(a, width, prec) for a in aligns]
            for w in words:
                for f in formats:
                    yield output(f,w)


def main():
    gen = generator.TestGenerator()
    gen.add_module('strings', 'case_1arg_s', globals())

    gjob = job.GenerateJob([], "test/testcases.inc", gen)

    compilers = compiler.find_compilers()
    cjobs = [ [ job.CompileJob([gjob], cc, "test/harness.cc"),
                job.CompileJob([], cc, "fmt.cc") ]
              for cc in compilers ]
    ljobs = [ job.LinkJob(objs, cc, "fmt")
              for (objs, cc) in zip(cjobs, compilers) ]
    tjobs = [ job.TestJob([ljob])
              for ljob in ljobs ]

    all = job.Job(tjobs)
    all.execute()

if __name__ == '__main__': main()


