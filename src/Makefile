include ../Makefile.base

TESTFILE ?= TransportLayer.bsv
TOPMODULE ?= mkAxiSTransportLayer
VLOG_FILE = $(VDIR)/$(TOPMODULE).list

../ruckus.tcl: verilog
	python3 ../ruckus_gen.py

verilog:
	mkdir -p $(BUILDDIR) $(VDIR)
	bsc -elab $(VERILOGFLAGS) $(DEBUGFLAGS) $(SRCDIRFLAGS) $(MISCFLAGS) $(RECOMPILEFLAGS) $(TRANSFLAGS) -g $(TOPMODULE) $(TESTFILE)
	echo "" >> $(VLOG_FILE)
	bluetcl ../listVlogFiles.tcl -bdir $(BUILDDIR) -vdir $(VDIR) $(TOPMODULE) $(TOPMODULE) | grep -i '\.v' >> $(VLOG_FILE)

clean:
	rm -rf $(BUILDDIR) $(VDIR) ../ruckus.tcl

.PHONY: verilog clean
