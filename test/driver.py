#
# In-tree main test driver.
#

assert __name__ == '__main__'

verbosity = 1

import compiler
import job

def main():
    testgen = job.RunJob([job.FileDep("test/test_fmt.py")],
                         ["test/test_fmt.py", "test/test_fmt.cc"],
                         output="test/test_fmt.cc")
    fmtccdep = job.FileDep("fmt.cc")
    fmthdep  = job.FileDep("fmt.h")

    compilers = compiler.find_compilers()
    cjobs = [ [ job.CompileJob([testgen, fmthdep], cc, "test/test_fmt.cc"),
                job.CompileJob([fmtccdep, fmthdep], cc, "fmt.cc") ]
              for cc in compilers ]
    ljobs = [ job.LinkJob(objs, cc, "fmt")
              for (objs, cc) in zip(cjobs, compilers) ]
    tjobs = [ job.TestJob([ljob], ["-q"])
              for ljob in ljobs ]

    all = job.Job(tjobs)
    all.execute()

main()
