# Test case generation utilities

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
