include ../Makefile.base

TESTFILE ?= TransportLayer.bsv
TOPMODULE ?= mkAxiSTransportLayer

verilog:
	mkdir -p $(BUILDDIR) $(VDIR)
	bsc -elab $(VERILOGFLAGS) $(DEBUGFLAGS) $(SRCDIRFLAGS) $(MISCFLAGS) $(RECOMPILEFLAGS) $(TRANSFLAGS) -g $(TOPMODULE) $(TESTFILE)

clean:
	rm -rf $(BUILDDIR) $(VDIR)

.PHONY: verilog clean
