import os
import itertools

dirname = "rtl"
rootdir = "../"
ext = ".list"

file_list = []

def listdir_fullpath(d):
    return [os.path.join(d, f) for f in os.listdir(d)]


for files in listdir_fullpath(dirname):
    if files.endswith(ext):
        with open(files) as f:
            file_list.append(f.read().splitlines())
    else:
        continue

fin_list = list(itertools.chain.from_iterable(file_list))
while("" in fin_list):
    fin_list.remove("")
fin_list = list(dict.fromkeys(fin_list))

with open(rootdir + '/ruckus.tcl', 'w') as fp:
    fp.write("""# Load RUCKUS library
source $::env(RUCKUS_PROC_TCL)

# Load sources (AUTOGENERATED - DO NOT EDIT!)
""")
    for item in fin_list:
        # write each item on a new line
        fp.write("loadSource -path \"%s\"\n" % item)

