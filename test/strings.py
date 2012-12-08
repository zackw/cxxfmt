#
# Generate formatting test cases for simple string constants.
#

import generator

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
        formats = ['{:' + (a+'{}').format(width) + '}' for a in aligns]
        for w in words:
            for f in formats:
                yield output(f,w)

def g_prec():
    for prec in xrange(maxw):
        formats = ['{:' + (a+'.{}').format(prec) + '}' for a in aligns]
        for w in words:
            for f in formats:
                yield output(f,w)

def g_wnp():
    for width in xrange(1, maxw):
        for prec in xrange(maxw):
            formats = ['{:' + (a+'{}.{}').format(width,prec) + '}'
                       for a in aligns]
            for w in words:
                for f in formats:
                    yield output(f,w)

def generate(outf):
    pass

if __name__ == '__main__':
    import sys
    generator.generate_mod(sys.stdout, 'strings', 'case_1arg_s', globals())

