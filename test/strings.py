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
    spec = '{:' + spec + '}'
    return '"{}", "{}", "{}"'.format(spec, spec.format(val), val)

def g_simple():
    for r in words:
        for a in aligns:
            yield output(a, r)

def g_width():
    for r in words:
        for w in xrange(1, maxw):
            for a in aligns:
                yield output('{}{}'.format(a, w), r)

def g_prec():
    for r in words:
        for p in xrange(maxw):
            for a in aligns:
                yield output('{}.{}'.format(a, p), r)

def g_wnp():
    for r in words:
        for w in xrange(1, maxw):
            for p in xrange(maxw):
                for a in aligns:
                    yield output('{}{}.{}'.format(a, w, p), r)

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


