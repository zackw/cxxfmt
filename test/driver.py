#
# In-tree main test driver.
#

assert __name__ == '__main__'

verbosity = 1

import compiler
import job

def main():
    gjob = job.RunJob([], ["test/test_fmt.py", "test/test_fmt.cc"])

    compilers = compiler.find_compilers()
    cjobs = [ [ job.CompileJob([gjob], cc, "test/test_fmt.cc"),
                job.CompileJob([], cc, "fmt.cc") ]
              for cc in compilers ]
    ljobs = [ job.LinkJob(objs, cc, "fmt")
              for (objs, cc) in zip(cjobs, compilers) ]
    tjobs = [ job.TestJob([ljob], ["-q"])
              for ljob in ljobs ]

    all = job.Job(tjobs)
    all.execute()

main()
