# Test case generation utilities

class TestBlock(object):
    def __init__(self, mod, name, casetype, generator):
        self.mod = mod
        self.name = name
        self.casetype = casetype
        self.generator = generator

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

    def emit(self, pattern, outf=None):
        txt = pattern.format(**vars(self))
        if outf is not None:
            outf.write(txt)
        return txt

    def fullname(self):
        return self.emit("{mod}.{name}")

    def write_cases(self, outf):
        self.emit("const {casetype} {mod}_{name}[] = {{\n", outf)
        for case in self.generator():
            outf.write("  { " + case + " },\n")
        outf.write("};\n\n")

    def write_tblock_obj(self, outf):
        self.emit("const tblock<{casetype}> "
                  "{mod}_{name}_b(\"{mod}.{name}\", {mod}_{name});\n", outf)

    def write_tblocks_entry(self, outf):
        self.emit("  &{mod}_{name}_b,\n", outf)

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

        outf.write("\nconst i_tblock *const tblocks[] = {\n")
        for b in self.blocks: b.write_tblocks_entry(outf)
        outf.write("};\nconst size_t n_tblocks = "
                   "sizeof(tblocks) / sizeof(tblocks[0]);")
